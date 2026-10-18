#include "sim/Bench.h"

#include <algorithm>
#include <cmath>

namespace sim {

namespace {
constexpr double kTwoPi = 6.283185307179586;
}

Bench::Bench(const MotorParams& motor, const BenchConfig& cfg)
    : cfg_(cfg), motor_(motor, cfg.inverter, cfg.supply, cfg.thermal), rng_(cfg.seed) {
  encoderAtPeak_ = encoderRead(motor_.angle());
}

float Bench::ampsPerCount() const {
  return static_cast<float>(cfg_.vref / 4096.0 / (cfg_.csaGain * cfg_.inverter.shunt));
}

float Bench::busVoltsPerCount() const { return static_cast<float>(cfg_.vref / 4096.0 / cfg_.busDivider); }

uint16_t Bench::senseCode(double amps, int phase, bool settled) {
  double volts = 0.5 * cfg_.vref + cfg_.csaOffsetVolts[phase];
  // Not settled: the CSA output is still slewing from the high-side interval. Model it as an
  // arbitrary reading (the firmware has to drop this phase, not average it).
  volts += settled ? cfg_.csaGain * cfg_.inverter.shunt * amps : 0.2 * cfg_.vref * gauss_(rng_);
  const double code = volts / cfg_.vref * 4096.0 + cfg_.csaNoiseCounts * gauss_(rng_);
  return static_cast<uint16_t>(std::clamp(std::lround(code), 0L, 4095L));
}

uint32_t Bench::encoderRead(double theta) {
  const double cpr = std::ldexp(1.0, cfg_.encoderBits);
  double turns = cfg_.encoderDirection * theta / kTwoPi + cfg_.encoderOffset;
  turns += cfg_.eccentricity * std::sin(theta + 0.7);
  double counts = std::floor((turns - std::floor(turns)) * cpr) + std::round(cfg_.encoderNoiseCounts * gauss_(rng_));
  counts = std::fmod(counts, cpr);
  if (counts < 0) counts += cpr;
  return static_cast<uint32_t>(counts);
}

uint16_t Bench::ntcCode(double celsius) {
  const double r = cfg_.ntcR25 * std::exp(cfg_.ntcBeta * (1.0 / (celsius + 273.15) - 1.0 / 298.15));
  const double code = 4096.0 * r / (r + cfg_.ntcPullup) + 0.7 * gauss_(rng_);
  return static_cast<uint16_t>(std::clamp(std::lround(code), 0L, 4095L));
}

uint16_t Bench::fetNtcCode() { return ntcCode(motor_.boardTemperature()); }
uint16_t Bench::motorNtcCode() { return ntcCode(motor_.motorTemperature()); }

foc::Sample Bench::sample() {
  foc::Sample s{};
  double i[3];
  motor_.phaseCurrents(i);
  const double window = cfg_.csaSettling * 2.0 / cfg_.pwmPeriod;  // duty above which the low side is too short
  for (int x = 0; x < 3; ++x) {
    const bool settled = !windowEnable_ || (1.0 - windowDuty_[x]) >= window;
    s.current[x] = senseCode(i[x], x, settled);
  }
  const double busCode = motor_.busVoltage() * cfg_.busDivider / cfg_.vref * 4096.0 + 0.8 * gauss_(rng_);
  s.bus = static_cast<uint16_t>(std::clamp(std::lround(busCode), 0L, 4095L));
  s.encoder = encoderAtPeak_;
  s.encoderFresh = encoderValid_;
  return s;
}

// DRV8353: a FET's V_DS above VDS_LVL while it conducts latches a shutdown (OCP_MODE = latched);
// V_M below the UVLO threshold holds the outputs off until it recovers.
void Bench::checkDriver() {
  undervoltage_ = motor_.busVoltage() < cfg_.undervoltage;
  if (!activeEnable_ || driverLatched_) return;
  double i[3];
  motor_.phaseCurrents(i);
  const double rds = cfg_.inverter.fetResistance * (1.0 + 0.006 * (motor_.boardTemperature() - 25.0));
  for (double x : i) {
    if (std::fabs(x) * rds > cfg_.vdsLevel) driverLatched_ = true;
  }
}

void Bench::step(const foc::Output& out) {
  const double T = cfg_.pwmPeriod;
  const int half = std::max(1, cfg_.substeps / 2);
  // This period runs on the duties written last tick; the encoder is read at its peak.
  for (int x = 0; x < 3; ++x) windowDuty_[x] = active_[x];
  windowEnable_ = activeEnable_ && !driverFault();
  motor_.step(active_, windowEnable_, T, 0.5 * T, half);
  checkDriver();
  encoderValid_ = magnet_;
  if (magnet_) encoderAtPeak_ = encoderRead(motor_.angle());
  motor_.step(active_, activeEnable_ && !driverFault(), T, 0.5 * T, half);
  checkDriver();
  active_[0] = out.duty.a;
  active_[1] = out.duty.b;
  active_[2] = out.duty.c;
  activeEnable_ = out.enable;
  time_ += T;
  ++ticks_;
}

}  // namespace sim
