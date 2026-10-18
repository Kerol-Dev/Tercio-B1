#include "app/Joint.h"

#include <cmath>

using foc::FocCore;

namespace {
float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
bool inMotion(Joint::State s) {
  return s == Joint::State::Holding || s == Joint::State::Moving || s == Joint::State::Velocity ||
         s == Joint::State::Torque || s == Joint::State::Impedance;
}
}  // namespace

void Joint::configure(const Settings& s) {
  settings_ = s;
  core_.configure(s.foc);
  outer_.setGains(s.gains);
  outer_.reset();
  trajectory_.reset(0);
  state_ = State::Disabled;
}

float Joint::torqueConstant() const {
  const FocCore::Config& c = core_.config();
  return 1.5f * static_cast<float>(c.polePairs) * c.fluxLinkage;
}

q32::Pos Joint::position() const {
  const FocCore::Config& c = core_.config();
  const EncoderTracker& e = core_.encoder();
  const bool forward = c.encoderDirection >= 0;
  const int64_t counts = forward ? e.counts() : -e.counts();
  const float extra = (forward ? 1.0f : -1.0f) * e.extrapolation() / static_cast<float>(1u << c.encoderBits);
  return q32::fromCounts(counts, c.encoderBits) + q32::fromDelta(extra);
}

float Joint::velocity() const {
  const FocCore::Config& c = core_.config();
  return (c.encoderDirection >= 0 ? 1.0f : -1.0f) * core_.encoder().velocity() /
         static_cast<float>(1u << c.encoderBits);
}

// ---- Real time ---------------------------------------------------------------------------------------------

foc::Output Joint::tick(const foc::Sample& s) {
  const FocCore::Config& c = core_.config();
  if (++ticks_ >= settings_.outerDivider) {
    ticks_ = 0;
    if (inMotion(state_)) {
      const float dt = c.tickPeriod * static_cast<float>(settings_.outerDivider);
      const q32::Pos p = position();
      const float v = velocity();
      const float kt = torqueConstant();
      const float maxTorque = kt * c.maxCurrent * derate_;
      OuterLoop::Reference ref;
      float tau = 0.0f;
      switch (state_) {
        case State::Torque:
          ref.torque = torqueCmd_;
          tau = outer_.update(OuterLoop::Mode::Torque, ref, p, v, maxTorque, torqueVelocityLimit_, dt);
          break;
        case State::Impedance:
          ref = {impPosition_, impVelocity_, impTorque_};
          tau = outer_.update(OuterLoop::Mode::Position, ref, p, v, maxTorque, settings_.maxVelocity, dt, impKp_,
                              impKd_);
          break;
        default:  // Holding, Moving, Velocity: follow the planner
          trajectory_.step(dt);
          if (state_ == State::Velocity) {
            // A held-back shaft drags the reference along instead of winding up a position error.
            const float lag = q32::diff(trajectory_.position(), p);
            const float w = settings_.followingWindow;
            if (std::fabs(lag) > w) {
              trajectory_.resync(p + q32::fromDelta(std::copysign(w, lag)), trajectory_.velocity());
            }
          }
          ref = {trajectory_.position(), trajectory_.velocity(), 0.0f};
          tau = outer_.update(OuterLoop::Mode::Position, ref, p, v, maxTorque, settings_.maxVelocity, dt);
          break;
      }
      torqueRef_ = tau;
      core_.setCurrent({0.0f, regenLimitedCurrent(kt > 0.0f ? tau / kt : 0.0f)});
    }
  }
  return core_.tick(s);
}

// Braking returns power to the bus: P = 1.5·(R·iq² + ωe·λ·iq). A bench supply cannot take it, so the
// braking current is limited to keep P ≥ −I_regen·V_bus, with I_regen fading to zero over the last
// `regenHeadroom` volts above the bus voltage seen at enable (and below the overvoltage trip).
float Joint::regenLimitedCurrent(float iq) {
  const FocCore::Config& c = core_.config();
  const float w = core_.electricalVelocity();
  if (iq * w >= 0.0f) return iq;
  const float vbus = core_.busVoltage();
  const float ceiling = std::fmin(regenStart_ + settings_.regenHeadroom, c.busOvervoltage - 1.0f);
  const float share = clampf((ceiling - vbus) / std::fmax(settings_.regenHeadroom, 0.1f), 0.0f, 1.0f);
  const float r = c.resistance;
  const float b = 1.5f * w * c.fluxLinkage;
  const float cc = settings_.maxRegenCurrent * share * vbus;
  float bound;
  if (r > 1e-6f) {
    const float disc = b * b - 6.0f * r * cc;
    if (disc <= 0.0f) return iq;  // copper losses absorb it all
    const float root = std::sqrt(disc);
    // The root nearer zero, on the braking side.
    bound = w > 0.0f ? (-b + root) / (3.0f * r) : (-b - root) / (3.0f * r);
  } else {
    bound = -cc / b;
  }
  if ((w > 0.0f && iq < bound) || (w < 0.0f && iq > bound)) {
    regenLimited_ = true;
    return bound;
  }
  return iq;
}

// ---- Main loop -------------------------------------------------------------------------------------------

float Joint::ntcCelsius(uint16_t code) const {
  const float k = clampf(static_cast<float>(code), 1.0f, 4094.0f);
  const float r = settings_.ntcPullup * k / (4096.0f - k);
  return 1.0f / (1.0f / 298.15f + std::log(r / settings_.ntcR25) / settings_.ntcBeta) - 273.15f;
}

void Joint::raise(uint16_t fault) {
  faults_ |= fault;
  if (fault & Fault::kHardMask) {
    if (calibration_.running()) calibration_.abort(core_);
    core_.setDrive(FocCore::Drive::Off);
    state_ = State::Fault;
  }
}

void Joint::update(const SlowSample& s) {
  // Temperatures (first-order filtered, τ ≈ 20 ms) and derating.
  fetTemperature_ += 0.05f * (ntcCelsius(s.fetNtc) - fetTemperature_);
  if (settings_.motorNtc) motorTemperature_ += 0.05f * (ntcCelsius(s.motorNtc) - motorTemperature_);
  float derate = clampf((settings_.fetOverTemperature - fetTemperature_) /
                            (settings_.fetOverTemperature - settings_.fetDerateStart), 0.0f, 1.0f);
  if (settings_.motorNtc) {
    derate = std::fmin(derate, clampf((settings_.motorOverTemperature - motorTemperature_) /
                                          (settings_.motorOverTemperature - settings_.motorDerateStart), 0.0f, 1.0f));
  }
  derate_ = derate;

  // Bridge off: the shunts carry no current, so the CSA codes are their zero. Track them (τ = 50 ms)
  // so every enable starts from fresh offsets (docs/07-firmware.md §7.6, step 1 at every enable).
  if ((state_ == State::Disabled || state_ == State::Fault) && core_.drive() == FocCore::Drive::Off) {
    const foc::Averages a = core_.takeAverages();
    if (a.ticks > 0 && offsetsTracked_++ > 20) {
      for (int x = 0; x < 3; ++x) core_.config().currentOffset[x] += 0.02f * (a.code[x] - core_.config().currentOffset[x]);
    }
  } else {
    offsetsTracked_ = 0;
  }

  uint16_t w = 0;
  if (derate_ < 1.0f) w |= Warning::kTemperatureHigh;
  if (!calibrated_) w |= Warning::kNotCalibrated;
  if (regenLimited_) w |= Warning::kRegenLimited;
  regenLimited_ = false;
  warnings_ = w;

  // Faults: the core's own (it has already switched the bridge off), the driver, temperatures.
  const uint16_t cf = core_.faults();
  if (cf & FocCore::kFaultOvercurrent) raise(Fault::kOverCurrent);
  if (cf & FocCore::kFaultEncoder) raise(Fault::kEncoder);
  if (cf & FocCore::kFaultOvervoltage) raise(Fault::kOverVoltage);
  if (cf & FocCore::kFaultUndervoltage) raise(Fault::kUnderVoltage);
  if (s.driverFault) raise(Fault::kDriverFault);
  if (fetTemperature_ >= settings_.fetOverTemperature) raise(Fault::kOverTemperature);
  if (settings_.motorNtc && motorTemperature_ >= settings_.motorOverTemperature) raise(Fault::kMotorOverTemperature);

  switch (state_) {
    case State::Calibrating:
      calibration_.update(core_);
      if (calibration_.phase() == Calibration::Phase::Done) {
        calibrated_ = true;
        state_ = State::Disabled;
      } else if (calibration_.phase() == Calibration::Phase::Failed) {
        state_ = State::Disabled;
        if (calibration_.error() != Calibration::Error::Aborted) faults_ |= Fault::kCalibrationFailed;
      }
      break;
    case State::Moving:
      if (trajectory_.done()) state_ = State::Holding;
      break;
    case State::Velocity:
    case State::Torque:
    case State::Impedance:
      if (settings_.commandTimeout > 0.0f && ++commandAgeMs_ > static_cast<uint32_t>(settings_.commandTimeout * 1000.0f)) {
        faults_ |= Fault::kCommandTimeout;
        stop();
      }
      break;
    default:
      break;
  }
}

// ---- Commands --------------------------------------------------------------------------------------------

void Joint::enterHold() {
  trajectory_.resync(position(), velocity());
  trajectory_.stop(settings_.maxAcceleration);
  state_ = State::Moving;
}

bool Joint::enable() {
  if (state_ == State::Fault || state_ == State::Calibrating || !calibrated_) return false;
  if (state_ != State::Disabled) return true;
  regenStart_ = core_.busVoltage();
  outer_.reset();
  trajectory_.reset(position());
  core_.setAngleSource(FocCore::AngleSource::Encoder);
  core_.setCurrent({0.0f, 0.0f});
  core_.setDrive(FocCore::Drive::Current);
  state_ = State::Holding;
  heartbeat();
  return true;
}

void Joint::disable() {
  if (calibration_.running()) calibration_.abort(core_);
  core_.setDrive(FocCore::Drive::Off);
  if (state_ != State::Fault) state_ = State::Disabled;
}

void Joint::stop() {
  if (!inMotion(state_)) return;
  if (state_ == State::Torque || state_ == State::Impedance) {
    enterHold();
    return;
  }
  trajectory_.stop(settings_.maxAcceleration);
  state_ = State::Moving;
}

bool Joint::moveTo(double turns, float maxVelocity, float maxAcceleration) {
  if (!inMotion(state_)) return false;
  if (state_ == State::Torque || state_ == State::Impedance) trajectory_.resync(position(), velocity());
  trajectory_.moveTo(q32::fromTurns(turns), clampf(maxVelocity, 0.01f, settings_.maxVelocity),
                     clampf(maxAcceleration, 0.1f, settings_.maxAcceleration));
  state_ = State::Moving;
  heartbeat();
  return true;
}

bool Joint::setVelocity(float turnsPerSecond, float maxAcceleration) {
  if (!inMotion(state_)) return false;
  if (state_ == State::Torque || state_ == State::Impedance) trajectory_.resync(position(), velocity());
  trajectory_.runAt(clampf(turnsPerSecond, -settings_.maxVelocity, settings_.maxVelocity),
                    clampf(maxAcceleration, 0.1f, settings_.maxAcceleration));
  state_ = State::Velocity;
  heartbeat();
  return true;
}

bool Joint::setTorque(float newtonMetres, float maxVelocity) {
  if (!inMotion(state_)) return false;
  torqueCmd_ = newtonMetres;
  torqueVelocityLimit_ = maxVelocity > 0.0f ? std::fmin(maxVelocity, settings_.maxVelocity) : settings_.maxVelocity;
  if (state_ != State::Torque) outer_.reset();
  state_ = State::Torque;
  heartbeat();
  return true;
}

bool Joint::impedance(double position, float velocity, float kp, float kd, float torque) {
  if (!inMotion(state_)) return false;
  impPosition_ = q32::fromTurns(position);
  impVelocity_ = velocity;
  impKp_ = std::fmax(kp, 0.0f);
  impKd_ = std::fmax(kd, 0.0f);
  impTorque_ = torque;
  if (state_ != State::Impedance) outer_.reset();
  state_ = State::Impedance;
  heartbeat();
  return true;
}

bool Joint::calibrate(const Calibration::Settings& s) {
  if (state_ != State::Disabled) return false;
  faults_ &= static_cast<uint16_t>(~Fault::kCalibrationFailed);
  calibrated_ = false;
  calibration_.start(core_, s);
  state_ = State::Calibrating;
  return true;
}

void Joint::clearFaults() {
  core_.clearFaults();
  faults_ = 0;
  if (state_ == State::Fault) state_ = State::Disabled;
}

Joint::Telemetry Joint::telemetry() const {
  Telemetry t;
  t.state = state_;
  t.faults = faults_;
  t.warnings = warnings_;
  t.position = q32::toTurns(position());
  t.velocity = velocity();
  const bool planner = state_ == State::Holding || state_ == State::Moving || state_ == State::Velocity;
  t.target = planner ? q32::toTurns(trajectory_.position()) : (state_ == State::Impedance ? q32::toTurns(impPosition_) : t.position);
  t.targetVelocity = planner ? trajectory_.velocity() : (state_ == State::Impedance ? impVelocity_ : t.velocity);
  t.torque = torqueConstant() * core_.current().q;
  t.torqueRef = inMotion(state_) ? torqueRef_ : 0.0f;
  t.idq = core_.current();
  t.vdq = core_.voltage();
  t.idqRef = inMotion(state_) ? foc::Dq{0.0f, torqueRef_ / std::fmax(torqueConstant(), 1e-9f)} : foc::Dq{0.0f, 0.0f};
  t.vbus = core_.busVoltage();
  t.ibus = t.vbus > 1.0f ? 1.5f * (t.vdq.d * t.idq.d + t.vdq.q * t.idq.q) / t.vbus : 0.0f;
  t.fetTemperature = fetTemperature_;
  t.motorTemperature = motorTemperature_;
  t.derate = derate_;
  t.calibration = calibration_.phase();
  return t;
}
