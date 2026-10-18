#include "foc/Calibration.h"

#include <cmath>

using foc::FocCore;

namespace {
constexpr uint32_t kOffsetSettleMs = 100, kOffsetMeasureMs = 500;
constexpr uint32_t kResistanceSettleMs = 500, kResistanceMeasureMs = 200;
constexpr float kRegulator = 125.7f;       // rad/s: pole of the slow voltage regulators (R and flux tests)
constexpr float kResistanceFloor = 0.02f;  // Ω: regulator gain floor before the first estimate
constexpr uint32_t kInductanceSkipMs = 10, kInductanceProbeMs = 100, kInductanceMeasureMs = 400;
constexpr float kInductanceDc = 0.6f;      // DC current, fraction of the calibration current
constexpr float kInductanceRipple = 1.2f;  // peak-to-peak ripple, fraction of the DC current
constexpr uint32_t kLockMs = 400, kHoldMs = 300, kScanSkipMs = 200;
constexpr float kMaxOffsetSpread = 0.05f;
constexpr uint32_t kFluxSettleMs = 300, kFluxMeasureMs = 300, kFluxRampTimeoutMs = 6000;
constexpr float kFluxRamp = 2.0f;  // V/s
constexpr float kDt = 1e-3f;       // the procedure's own period

uint32_t scanMs(float turns, float speed) {
  return static_cast<uint32_t>(turns * foc::kTwoPi / speed * 1000.0f + 0.5f);
}
}  // namespace

void Calibration::start(FocCore& core, const Settings& s) {
  settings_ = s;
  result_ = Result{};
  error_ = Error::None;
  core.takeAverages();
  enter(core, Phase::Offsets);
}

void Calibration::abort(FocCore& core) {
  if (running()) fail(core, Error::Aborted);
}

void Calibration::fail(FocCore& core, Error e) {
  core.setDrive(FocCore::Drive::Off);
  error_ = e;
  phase_ = Phase::Failed;
}

void Calibration::clearSums() {
  for (double& s : sum_) s = 0.0;
  weight_ = 0.0;
}

void Calibration::enter(FocCore& core, Phase p) {
  phase_ = p;
  ms_ = 0;
  sub_ = 0;
  clearSums();
  switch (p) {
    case Phase::Offsets:
    case Phase::Done:
      core.setDrive(FocCore::Drive::Off);
      break;
    case Phase::Resistance:
      volts_ = 0.0f;
      resistanceEstimate_ = 0.0f;
      core.setAngleSource(FocCore::AngleSource::Commanded);
      core.setCommandedAngle(0, 0.0f);
      core.setVoltage({0.0f, 0.0f});
      core.setDrive(FocCore::Drive::Voltage);
      break;
    case Phase::Inductance:
      // Probe: a small square wave (ripple ≤ ¼ of the DC current for any R·T/L ≤ 1) on top of
      // kInductanceDc·I, to size the real test.
      testOffset_ = resistanceIntercept_ + result_.resistance * kInductanceDc * settings_.current;
      testVolts_ = 0.25f * testOffset_;
      halfPeriod_ = 1;
      core.setAngleSource(FocCore::AngleSource::Commanded);
      core.setCommandedAngle(0, 0.0f);
      core.setInductanceTest(testOffset_, testVolts_, halfPeriod_);
      core.setDrive(FocCore::Drive::Inductance);
      break;
    case Phase::PolePairs:
      core.setAngleSource(FocCore::AngleSource::Commanded);
      core.setCommandedAngle(0, 0.0f);
      core.setCurrent({settings_.current, 0.0f});
      core.setDrive(FocCore::Drive::Current);
      break;
    case Phase::EncoderOffset:
      scanMs_ = scanMs(settings_.offsetScanTurns, settings_.scanSpeed);
      core.setCommandedAngle(core.commandedAngle(), -settings_.scanSpeed);
      break;
    case Phase::FluxLinkage:
      volts_ = 0.0f;
      for (auto& row : point_) for (double& v : row) v = 0.0;
      core.setAngleSource(FocCore::AngleSource::Encoder);
      core.setVoltage({0.0f, 0.0f});
      core.setDrive(FocCore::Drive::Voltage);
      break;
    default:
      break;
  }
}

void Calibration::update(FocCore& core) {
  if (!running()) return;
  const foc::Averages a = core.takeAverages();
  if (core.faults()) {
    fail(core, Error::Fault);
    return;
  }
  ++ms_;
  switch (phase_) {
    case Phase::Offsets: updateOffsets(core, a); break;
    case Phase::Resistance: updateResistance(core, a); break;
    case Phase::Inductance: updateInductance(core, a); break;
    case Phase::PolePairs: updatePolePairs(core, a); break;
    case Phase::EncoderOffset: updateEncoderOffset(core, a); break;
    case Phase::FluxLinkage: updateFlux(core, a); break;
    default: break;
  }
}

// ---- 1. CSA zero codes, bridge off -------------------------------------------------------------------------
void Calibration::updateOffsets(FocCore& core, const foc::Averages& a) {
  if (ms_ <= kOffsetSettleMs) return;
  for (int x = 0; x < 3; ++x) sum_[x] += static_cast<double>(a.code[x]) * a.ticks;
  weight_ += a.ticks;
  if (ms_ < kOffsetSettleMs + kOffsetMeasureMs || weight_ <= 0.0) return;
  for (int x = 0; x < 3; ++x) {
    result_.offset[x] = static_cast<float>(sum_[x] / weight_);
    core.config().currentOffset[x] = result_.offset[x];
  }
  enter(core, Phase::Resistance);
}

// ---- 2. Resistance: slow voltage regulator to ½·I, then I --------------------------------------------------
void Calibration::updateResistance(FocCore& core, const foc::Averages& a) {
  const float level = (sub_ == 0 ? 0.5f : 1.0f) * settings_.current;
  const float id = a.idq.d;
  if (id > 0.1f * level && volts_ > 0.0f) {
    const float r = volts_ / id;
    resistanceEstimate_ = resistanceEstimate_ > 0.0f ? resistanceEstimate_ + 0.1f * (r - resistanceEstimate_) : r;
  }
  // Integral regulator with its gain scaled by R, so the loop pole sits at kRegulator for any winding.
  const float gain = std::fmax(resistanceEstimate_, kResistanceFloor) * kRegulator;
  volts_ = foc::clamp(volts_ + gain * (level - id) * kDt, 0.0f, settings_.maxVoltage);
  core.setVoltage({volts_, 0.0f});
  if (volts_ >= settings_.maxVoltage && id < 0.5f * level && ms_ > 200) {
    fail(core, Error::NoCurrent);
    return;
  }
  if (ms_ > kResistanceSettleMs) {
    sum_[2 * sub_] += static_cast<double>(a.vdq.d) * a.ticks;
    sum_[2 * sub_ + 1] += static_cast<double>(a.idq.d) * a.ticks;
    sum_[4 + sub_] += a.ticks;
  }
  if (ms_ < kResistanceSettleMs + kResistanceMeasureMs) return;
  if (sub_ == 0) {
    sub_ = 1;
    ms_ = 0;
    return;
  }
  const double v1 = sum_[0] / sum_[4], i1 = sum_[1] / sum_[4];
  const double v2 = sum_[2] / sum_[5], i2 = sum_[3] / sum_[5];
  const double r = (v2 - v1) / (i2 - i1);
  if (!(i2 - i1 > 0.2 * static_cast<double>(settings_.current)) || !(r > 1e-3 && r < 200.0)) {
    fail(core, Error::Resistance);
    return;
  }
  result_.resistance = static_cast<float>(r);
  resistanceIntercept_ = static_cast<float>(v1 - r * i1);
  core.config().resistance = result_.resistance;
  enter(core, Phase::Inductance);
}

// ---- 3. Inductance: Δi = γ + α·s + β·m per tick, L = V·T/α ------------------------------------------------
namespace {
// Least squares for Δ = γ + α·s + β·m from the sums; returns α (0 if singular).
double squareWaveSlope(const double* sum) {
  const double n = sum[0], ss = sum[1], sm = sum[2], sd = sum[3];
  const double ssm = sum[4], smm = sum[5], ssd = sum[6], smd = sum[7];
  // Normal equations [n ss sm; ss n ssm; sm ssm smm]·[γ α β] = [sd ssd smd] (s² = 1), Cramer's rule for α.
  const double det = n * (n * smm - ssm * ssm) - ss * (ss * smm - ssm * sm) + sm * (ss * ssm - n * sm);
  if (!(std::fabs(det) > 0.0)) return 0.0;
  const double num = n * (ssd * smm - ssm * smd) - sd * (ss * smm - ssm * sm) + sm * (ss * smd - ssd * sm);
  return num / det;
}
}  // namespace

void Calibration::updateInductance(FocCore& core, const foc::Averages& a) {
  if (ms_ <= kInductanceSkipMs) return;  // the DC current and the ripple settle first
  sum_[0] += a.inductanceTicks;
  sum_[1] += static_cast<double>(a.sumS);
  sum_[2] += static_cast<double>(a.sumM);
  sum_[3] += static_cast<double>(a.sumD);
  sum_[4] += static_cast<double>(a.sumSM);
  sum_[5] += static_cast<double>(a.sumMM);
  sum_[6] += static_cast<double>(a.sumSD);
  sum_[7] += static_cast<double>(a.sumMD);
  if (ms_ < kInductanceSkipMs + (sub_ == 0 ? kInductanceProbeMs : kInductanceMeasureMs)) return;

  const double alpha = squareWaveSlope(sum_);
  const double period = static_cast<double>(core.config().tickPeriod);
  const double l = alpha > 0.0 ? static_cast<double>(testVolts_) * period / alpha : 0.0;
  if (!(l > 0.5e-6 && l < 0.2)) {
    fail(core, Error::Inductance);
    return;
  }
  if (sub_ == 0) {
    // Size the real test: ripple kInductanceRipple·I_dc peak to peak (never reaching zero), from the
    // largest square wave that fits, then longer half-periods if needed, at most L/R each.
    const double idc = static_cast<double>(kInductanceDc * settings_.current);
    const double ripple = static_cast<double>(kInductanceRipple) * idc;
    const FocCore::Config& c = core.config();
    const double vmax = static_cast<double>(c.maxModulation * foc::linearLimit(core.busVoltage()));
    const double room = std::fmax(0.05, std::fmin(0.4 * vmax, vmax - static_cast<double>(testOffset_) - 0.5));
    const double v = std::fmin(ripple * l / period, room);
    const double r = static_cast<double>(result_.resistance);
    double m = std::floor(ripple * l / (v * period));
    m = std::fmin(m, std::floor(l / (r * period)));
    testVolts_ = static_cast<float>(v);
    halfPeriod_ = static_cast<uint16_t>(std::fmax(1.0, std::fmin(32.0, m)));
    core.setInductanceTest(testOffset_, testVolts_, halfPeriod_);
    sub_ = 1;
    ms_ = 0;
    clearSums();
    return;
  }
  result_.inductance = static_cast<float>(l);
  FocCore::Config& c = core.config();
  c.inductanceD = c.inductanceQ = result_.inductance;
  c.currentGains = CurrentLoop::forMotor(result_.resistance, result_.inductance, settings_.bandwidth);
  enter(core, Phase::PolePairs);
}

// ---- 4. Pole pairs and direction: N electrical turns against the encoder ----------------------------------
void Calibration::updatePolePairs(FocCore& core, const foc::Averages&) {
  if (sub_ == 0) {  // locked at θ = 0
    if (ms_ < kLockMs) return;
    startCounts_ = core.encoder().counts();
    scanMs_ = scanMs(settings_.poleScanTurns, settings_.scanSpeed);
    core.setCommandedAngle(core.commandedAngle(), settings_.scanSpeed);
    sub_ = 1;
    ms_ = 0;
  } else if (sub_ == 1) {  // rotating
    if (ms_ < scanMs_) return;
    core.setCommandedAngle(core.commandedAngle(), 0.0f);
    sub_ = 2;
    ms_ = 0;
  } else {  // holding: both end points are at rest, so friction lag is the same at each
    if (ms_ < kHoldMs) return;
    const int64_t delta = core.encoder().counts() - startCounts_;
    const double cpr = std::ldexp(1.0, core.config().encoderBits);
    const double turns = static_cast<double>(delta) / cpr;
    const double electrical = static_cast<double>(settings_.scanSpeed) * scanMs_ * 1e-3 / static_cast<double>(foc::kTwoPi);
    if (std::fabs(turns) < 0.01) {
      fail(core, Error::NoMotion);
      return;
    }
    const double ratio = electrical / std::fabs(turns);
    const long pp = std::lround(ratio);
    if (pp < 1 || pp > 60 || std::fabs(ratio - static_cast<double>(pp)) > 0.25) {
      fail(core, Error::PolePairs);
      return;
    }
    result_.polePairs = static_cast<uint8_t>(pp);
    result_.direction = delta > 0 ? 1 : -1;
    core.config().polePairs = result_.polePairs;
    core.config().encoderDirection = result_.direction;
    enter(core, Phase::EncoderOffset);
  }
}

// ---- 5. Encoder offset: circular mean of (commanded − encoder), backward then forward -------------------
void Calibration::updateEncoderOffset(FocCore& core, const foc::Averages&) {
  if (ms_ > kScanSkipMs) {
    const foc::Angle off = core.angle() - core.electricalFromRaw(core.encoder().raw());
    const float r = foc::toRadians(off);
    sum_[0] += static_cast<double>(std::cos(r));
    sum_[1] += static_cast<double>(std::sin(r));
    weight_ += 1.0;
  }
  if (ms_ < kScanSkipMs + scanMs_) return;
  if (sub_ == 0) {
    core.setCommandedAngle(core.commandedAngle(), settings_.scanSpeed);
    sub_ = 1;
    ms_ = 0;
    return;
  }
  core.setCommandedAngle(core.commandedAngle(), 0.0f);
  const double mean = std::atan2(sum_[1], sum_[0]);
  result_.offsetSpread = static_cast<float>(1.0 - std::hypot(sum_[0], sum_[1]) / weight_);
  if (result_.offsetSpread > kMaxOffsetSpread) {
    fail(core, Error::EncoderNoise);
    return;
  }
  result_.encoderOffset = foc::fromRadians(static_cast<float>(mean));
  core.config().encoderOffset = result_.encoderOffset;
  enter(core, settings_.flux ? Phase::FluxLinkage : Phase::Done);
}

// ---- 6. Flux linkage: q voltage on the encoder angle, two self-regulated speeds ---------------------------
void Calibration::updateFlux(FocCore& core, const foc::Averages& a) {
  const FocCore::Config& c = core.config();
  const float r = result_.resistance, l = result_.inductance, limit = settings_.current;
  const float emf = a.vdq.q - r * a.idq.q;
  const float mechanical = std::fabs(a.omega) / static_cast<float>(c.polePairs);
  const int point = sub_ / 2;

  if (sub_ == 0 || sub_ == 2) {  // ramp v_q until the back-EMF (or the speed cap) reaches its target
    const float vmax = 0.9f * c.maxModulation * foc::linearLimit(a.vbus);
    if (std::fabs(a.idq.q) > limit) {
      volts_ -= std::fmax(r, kResistanceFloor) * kRegulator * (std::fabs(a.idq.q) - limit) * kDt;
    } else {
      volts_ += kFluxRamp * kDt;
    }
    volts_ = foc::clamp(volts_, 0.0f, vmax);
    core.setVoltage({0.0f, volts_});
    const float k = sub_ == 0 ? 0.5f : 1.0f;
    if (emf >= k * settings_.fluxEmf || mechanical >= k * settings_.fluxMaxSpeed) {
      ++sub_;
      ms_ = 0;
    } else if (ms_ > kFluxRampTimeoutMs) {
      fail(core, Error::Flux);
    }
    return;
  }

  // Holding v_q: the speed settles where the back-EMF balances it.
  if (ms_ > kFluxSettleMs) {
    point_[point][0] += static_cast<double>(emf) * a.ticks;
    point_[point][1] += static_cast<double>(a.omega) * a.ticks;
    point_[point][2] += static_cast<double>(l * a.idq.d * a.omega) * a.ticks;
    point_[point][3] += a.ticks;
  }
  if (ms_ < kFluxSettleMs + kFluxMeasureMs) return;
  if (sub_ == 1) {
    sub_ = 2;
    ms_ = 0;
    return;
  }
  double m[2][3];
  for (int k = 0; k < 2; ++k) {
    for (int j = 0; j < 3; ++j) m[k][j] = point_[k][j] / point_[k][3];
  }
  const double dw = m[1][1] - m[0][1];
  const double lambda = ((m[1][0] - m[0][0]) - (m[1][2] - m[0][2])) / dw;
  if (!(dw > 0.2 * m[1][1]) || !(lambda > 1e-5 && lambda < 0.5)) {
    fail(core, Error::Flux);
    return;
  }
  result_.fluxLinkage = static_cast<float>(lambda);
  core.config().fluxLinkage = result_.fluxLinkage;
  enter(core, Phase::Done);
}
