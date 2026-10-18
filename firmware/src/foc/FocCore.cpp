#include "foc/FocCore.h"

namespace foc {

namespace {

Dq limitMagnitude(Dq v, float limit) {
  const float m2 = v.d * v.d + v.q * v.q;
  if (m2 <= limit * limit) return v;
  const float k = limit / std::sqrt(m2);
  return {v.d * k, v.q * k};
}

}  // namespace

void FocCore::configure(const Config& c) {
  config_ = c;
  tracker_.configure(c.encoderBits, c.tickPeriod, c.velocityBandwidth);
  loop_.setGains(c.currentGains);
  loop_.reset();
  trackerStarted_ = false;
}

void FocCore::setDrive(Drive d) {
  if (d != drive_) {
    loop_.reset();
    predicted_ = idq_;
    testCount_ = 0;
    testSign_ = 1.0f;
  }
  drive_ = d;
}

void FocCore::setCommandedAngle(Angle a, float omega) {
  angleCmd_ = a;
  omegaCmd_ = omega;
  angleStep_ = static_cast<int32_t>(omega * config_.tickPeriod * kAnglePerRad);
}

void FocCore::setInductanceTest(float offsetVolts, float volts, uint16_t halfPeriod) {
  testOffset_ = offsetVolts;
  testVolts_ = volts;
  testHalfPeriod_ = halfPeriod > 0 ? halfPeriod : 1;
  testCount_ = 0;
  testSign_ = 1.0f;
}

Angle FocCore::electricalFromRaw(uint32_t raw) const {
  // raw < 2^21 and polePairs < 256, so the product fits before the shift drops whole turns.
  const Angle e = (raw * config_.polePairs) << (32 - config_.encoderBits);
  return config_.encoderDirection >= 0 ? e : static_cast<Angle>(0u - e);
}

Averages FocCore::takeAverages() {
  Averages a = acc_;
  acc_ = Averages{};
  if (a.ticks == 0) return a;
  const float k = 1.0f / static_cast<float>(a.ticks);
  for (float& c : a.code) c *= k;
  a.i = {a.i.a * k, a.i.b * k, a.i.c * k};
  a.idq = {a.idq.d * k, a.idq.q * k};
  a.vdq = {a.vdq.d * k, a.vdq.q * k};
  a.vbus *= k;
  a.omega *= k;
  return a;
}

Output FocCore::tick(const Sample& s) {
  const Config& c = config_;
  const float T = c.tickPeriod;

  // ---- 1. Currents and bus voltage ---------------------------------------------------------------------
  float i[3];
  for (int x = 0; x < 3; ++x) i[x] = (static_cast<float>(s.current[x]) - c.currentOffset[x]) * c.ampsPerCount;
  // Near full modulation one phase's low-side window is too short for its CSA to settle
  // before the valley: drop the phase with the highest duty and use ia + ib + ic = 0.
  if (enableHistory_[1]) {
    const Duty3& d = dutyHistory_[1];
    int worst = 0;
    float dmax = d.a;
    if (d.b > dmax) dmax = d.b, worst = 1;
    if (d.c > dmax) dmax = d.c, worst = 2;
    if ((1.0f - dmax) * 0.5f * T < c.sampleWindow) i[worst] = -(i[(worst + 1) % 3] + i[(worst + 2) % 3]);
  }
  iabc_ = {i[0], i[1], i[2]};
  vbus_ = static_cast<float>(s.bus) * c.busVoltsPerCount;

  // ---- 2. Encoder: multi-turn count, velocity, electrical angle -----------------------------------------
  if (trackerStarted_) {
    tracker_.update(s.encoderFresh, s.encoder);
  } else if (s.encoderFresh) {
    tracker_.reset(static_cast<int64_t>(s.encoder), s.encoder);  // absolute within the first turn
    trackerStarted_ = true;
  }
  const float radPerCount = kTwoPi / static_cast<float>(1u << c.encoderBits);
  omega_ = static_cast<float>(c.encoderDirection) * tracker_.velocity() * radPerCount *
           static_cast<float>(c.polePairs);
  // The sample is `encoderLead` ticks older than the currents, plus any ticks without a fresh one.
  const float age = static_cast<float>(tracker_.ticksSinceSample()) + c.encoderLead;
  const Angle encoderAngle =
      electricalFromRaw(tracker_.raw()) + c.encoderOffset + fromRadians(omega_ * age * T);

  Angle outAngle;
  if (angleSource_ == AngleSource::Commanded) {
    angle_ = angleCmd_;
    outAngle = angleCmd_ + fromRadians(omegaCmd_ * c.outputDelay * T);
    angleCmd_ += static_cast<Angle>(angleStep_);
  } else {
    angle_ = encoderAngle;
    outAngle = encoderAngle + fromRadians(omega_ * c.outputDelay * T);
  }
  float sn, cs;
  sinCos(angle_, sn, cs);
  idq_ = park(clarke(iabc_), sn, cs);

  // ---- 3. Protection -----------------------------------------------------------------------------------
  bool on = drive_ != Drive::Off;
  for (float x : i) {
    if (std::fabs(x) > c.overcurrentTrip) faults_ |= kFaultOvercurrent;
  }
  if (vbus_ > c.busOvervoltage) {
    if (++overvoltageTicks_ >= 3) faults_ |= kFaultOvervoltage;
  } else {
    overvoltageTicks_ = 0;
  }
  if (on && vbus_ < c.busUndervoltage) faults_ |= kFaultUndervoltage;
  if (on && angleSource_ == AngleSource::Encoder &&
      (!trackerStarted_ || tracker_.ticksSinceSample() > c.encoderTimeout)) {
    faults_ |= kFaultEncoder;
  }
  if (faults_) on = false;

  // ---- 4. Drive ----------------------------------------------------------------------------------------
  const float vmax = c.maxModulation * linearLimit(vbus_);
  Dq v{0.0f, 0.0f};
  float sign = 0.0f;
  if (!on) {
    loop_.reset();
    predicted_ = {0.0f, 0.0f};
  } else if (drive_ == Drive::Voltage) {
    v = limitMagnitude(voltageRef_, vmax);
  } else if (drive_ == Drive::Current) {
    const Dq ref = limitMagnitude(currentRef_, c.maxCurrent);
    // Decoupling acts on the current the loop will have produced, not on a step it has not
    // followed yet: the reference through a first-order model of the closed loop (ωc = kp/L).
    const float wc = c.inductanceQ > 0.0f ? c.currentGains.kp / c.inductanceQ : 0.0f;
    const float k = clamp(wc * T, 0.0f, 1.0f);
    predicted_ = {predicted_.d + k * (ref.d - predicted_.d), predicted_.q + k * (ref.q - predicted_.q)};
    Dq ff{0.0f, 0.0f};
    if (c.decoupling && angleSource_ == AngleSource::Encoder) {
      ff.d = -omega_ * c.inductanceQ * predicted_.q;
      ff.q = omega_ * (c.inductanceD * predicted_.d + c.fluxLinkage);
    }
    loop_.setGains(c.currentGains);
    v = loop_.update(ref, idq_, ff, vmax, T);
  } else if (drive_ == Drive::Inductance) {
    sign = testSign_;
    v = {clamp(testOffset_ + sign * testVolts_, -vmax, vmax), 0.0f};
    if (++testCount_ >= testHalfPeriod_) {
      testCount_ = 0;
      testSign_ = -testSign_;
    }
  }
  vdq_ = v;

  Output out;
  out.enable = on;
  if (on) {
    sinCos(outAngle, sn, cs);
    out.duty = svpwm(inversePark(v, sn, cs), vbus_);
  } else {
    out.duty = {0.5f, 0.5f, 0.5f};
  }

  // ---- 5. Statistics -----------------------------------------------------------------------------------
  // Inductance test: the voltage that acted between the last sample and this one was written
  // two ticks ago (one tick of TIM1 preload, then one period active).
  const float di = idq_.d - previousId_;
  const float mid = 0.5f * (idq_.d + previousId_);
  previousId_ = idq_.d;
  if (on && signHistory_[1] != 0.0f) {
    const float s2 = signHistory_[1];
    acc_.sumS += s2;
    acc_.sumM += mid;
    acc_.sumD += di;
    acc_.sumSD += s2 * di;
    acc_.sumMD += mid * di;
    acc_.sumSM += s2 * mid;
    acc_.sumMM += mid * mid;
    ++acc_.inductanceTicks;
  }
  ++acc_.ticks;
  for (int x = 0; x < 3; ++x) acc_.code[x] += static_cast<float>(s.current[x]);
  acc_.i = {acc_.i.a + i[0], acc_.i.b + i[1], acc_.i.c + i[2]};
  acc_.idq = {acc_.idq.d + idq_.d, acc_.idq.q + idq_.q};
  acc_.vdq = {acc_.vdq.d + v.d, acc_.vdq.q + v.q};
  acc_.vbus += vbus_;
  acc_.omega += omega_;

  dutyHistory_[1] = dutyHistory_[0];
  dutyHistory_[0] = out.duty;
  enableHistory_[1] = enableHistory_[0];
  enableHistory_[0] = out.enable;
  signHistory_[1] = signHistory_[0];
  signHistory_[0] = sign;
  return out;
}

}  // namespace foc
