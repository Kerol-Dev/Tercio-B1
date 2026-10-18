#include "sim/Motor.h"

#include <algorithm>
#include <cmath>

namespace sim {

namespace {
constexpr double kSqrt3 = 1.7320508075688772;
constexpr double kNodeCurrent = 0.2;     // A: dead-time error fades in over this current
constexpr double kStictionSpeed = 0.01;  // rad/s: Coulomb friction fades in over this speed
constexpr double kCopperTempco = 0.00393;
constexpr double kFetTempco = 0.006;
constexpr double kBrownout = 5.0;        // V: below this the board's logic draws nothing
}  // namespace

Motor::Motor(const MotorParams& m, const InverterParams& inv, const SupplyParams& sup, const ThermalParams& th)
    : m_(m), inv_(inv), sup_(sup), th_(th) {
  vbus_ = sup_.connected ? sup_.volts : 0.0;
  boardT_ = motorT_ = th_.ambient;
}

void Motor::setMechanics(Mechanics mode, double speed) {
  mechanics_ = mode;
  if (mode == Mechanics::Speed) omega_ = speed;
  if (mode == Mechanics::Locked) omega_ = 0.0;
}

double Motor::resistance() const { return m_.resistance * (1.0 + kCopperTempco * (motorT_ - 25.0)); }

double Motor::legResistance() const {
  return inv_.fetResistance * (1.0 + kFetTempco * (boardT_ - 25.0)) + inv_.shunt;
}

void Motor::phaseCurrents(double out[3]) const {
  const double e = m_.polePairs * theta_;
  const double c = std::cos(e), s = std::sin(e);
  const double alpha = id_ * c - iq_ * s, beta = id_ * s + iq_ * c;
  out[0] = alpha;
  out[1] = -0.5 * alpha + 0.5 * kSqrt3 * beta;
  out[2] = -0.5 * alpha - 0.5 * kSqrt3 * beta;
}

double Motor::torque() const {
  return 1.5 * m_.polePairs * (m_.fluxLinkage * iq_ + (m_.inductanceD - m_.inductanceQ) * id_ * iq_);
}

double Motor::supplyCurrentAt(double vbus) const {
  if (!sup_.connected) return 0.0;
  const double i = (sup_.volts - vbus) / sup_.resistance;
  if (sup_.kind == SupplyParams::Kind::Bench) return std::clamp(i, 0.0, sup_.currentLimit);  // cannot sink
  return i;
}

Motor::State Motor::derivative(const State& s, const double* duty) const {
  State d{0.0, 0.0, 0.0, s.omega, 0.0};
  const double p = m_.polePairs;
  const double e = p * s.theta;
  const double c = std::cos(e), sn = std::sin(e);
  const double we = p * s.omega;
  double idc = 0.0;

  if (duty) {
    const double ia = s.id * c - s.iq * sn, ib = s.id * sn + s.iq * c;  // α, β
    const double i[3] = {ia, -0.5 * ia + 0.5 * kSqrt3 * ib, -0.5 * ia - 0.5 * kSqrt3 * ib};
    const double vbus = std::max(s.vbus, 0.0);
    const double vdt = inv_.deadTime / pwmPeriod_ * vbus;
    const double rleg = legResistance();
    double u[3];
    for (int x = 0; x < 3; ++x) {
      u[x] = duty[x] * vbus - std::tanh(i[x] / kNodeCurrent) * vdt - rleg * i[x];
      idc += duty[x] * i[x];
    }
    const double alpha = (2.0 * u[0] - u[1] - u[2]) / 3.0, beta = (u[1] - u[2]) / kSqrt3;
    const double vd = alpha * c + beta * sn, vq = -alpha * sn + beta * c;
    const double r = resistance();
    d.id = (vd - r * s.id + we * m_.inductanceQ * s.iq) / m_.inductanceD;
    d.iq = (vq - r * s.iq - we * (m_.inductanceD * s.id + m_.fluxLinkage)) / m_.inductanceQ;
  }

  const double logic = s.vbus > kBrownout ? sup_.logicCurrent : 0.0;
  d.vbus = (supplyCurrentAt(s.vbus) - idc - logic) / sup_.capacitance;

  if (mechanics_ == Mechanics::Free) {
    const double te = 1.5 * p * (m_.fluxLinkage * s.iq + (m_.inductanceD - m_.inductanceQ) * s.id * s.iq);
    const double friction = (m_.viscous + brake_) * s.omega + m_.coulomb * std::tanh(s.omega / kStictionSpeed);
    const double cog = m_.cogging * std::sin(m_.coggingPerTurn * s.theta);
    d.omega = (te - friction - cog - load_) / (m_.inertia + extraInertia_);
  }
  return d;
}

void Motor::step(const double duty[3], bool enabled, double pwmPeriod, double dt, int substeps) {
  pwmPeriod_ = pwmPeriod;
  if (!enabled) id_ = iq_ = 0.0;
  const double* u = enabled ? duty : nullptr;
  const double h = dt / substeps;
  const auto add = [](const State& a, const State& k, double f) {
    return State{a.id + f * k.id, a.iq + f * k.iq, a.omega + f * k.omega, a.theta + f * k.theta, a.vbus + f * k.vbus};
  };
  for (int n = 0; n < substeps; ++n) {
    const State s0{id_, iq_, omega_, theta_, vbus_};
    const State k1 = derivative(s0, u);
    const State k2 = derivative(add(s0, k1, 0.5 * h), u);
    const State k3 = derivative(add(s0, k2, 0.5 * h), u);
    const State k4 = derivative(add(s0, k3, h), u);
    id_ += h / 6.0 * (k1.id + 2.0 * k2.id + 2.0 * k3.id + k4.id);
    iq_ += h / 6.0 * (k1.iq + 2.0 * k2.iq + 2.0 * k3.iq + k4.iq);
    omega_ += h / 6.0 * (k1.omega + 2.0 * k2.omega + 2.0 * k3.omega + k4.omega);
    theta_ += h / 6.0 * (k1.theta + 2.0 * k2.theta + 2.0 * k3.theta + k4.theta);
    vbus_ += h / 6.0 * (k1.vbus + 2.0 * k2.vbus + 2.0 * k3.vbus + k4.vbus);
  }
  vbus_ = std::max(vbus_, 0.0);
  supplyCurrent_ = supplyCurrentAt(vbus_);

  // Losses and temperatures, once per step (thermal time constants are seconds).
  const double i2 = id_ * id_ + iq_ * iq_;  // Σ i_x² = 1.5·|i|²
  double sumAbs = 0.0;
  if (enabled) {
    double i[3];
    phaseCurrents(i);
    sumAbs = std::fabs(i[0]) + std::fabs(i[1]) + std::fabs(i[2]);
  }
  const bool powered = vbus_ > kBrownout;
  boardLoss_ = (enabled ? 1.5 * i2 * legResistance() + vbus_ * sumAbs * inv_.switchingTime / pwmPeriod : 0.0) +
               (powered ? (enabled ? inv_.logicPower : 0.4 * inv_.logicPower) : 0.0);
  motorLoss_ = 1.5 * i2 * resistance();
  boardT_ += dt / th_.boardCapacity * (boardLoss_ - (boardT_ - th_.ambient) / th_.boardResistance);
  motorT_ += dt / m_.thermalCapacity * (motorLoss_ - (motorT_ - th_.ambient) / m_.thermalResistance);
}

namespace motors {

MotorParams gimbal() {
  MotorParams m;
  m.name = "gimbal 2804";
  m.resistance = 5.0;
  m.inductanceD = m.inductanceQ = 2.0e-3;
  m.fluxLinkage = 5.25e-3;
  m.polePairs = 7;
  m.inertia = 2e-5;
  m.viscous = 2e-5;
  m.coulomb = 1e-3;
  m.cogging = 2e-3;
  m.coggingPerTurn = 84;
  m.thermalCapacity = 15.0;
  m.thermalResistance = 10.0;
  m.ratedCurrent = 1.5;
  return m;
}

MotorParams qdd5010() {
  MotorParams m;
  m.name = "QDD 5010";
  m.resistance = 0.10;
  m.inductanceD = m.inductanceQ = 40e-6;
  m.fluxLinkage = 1.09e-3;
  m.polePairs = 14;
  m.inertia = 6e-5;
  m.viscous = 1e-5;
  m.coulomb = 0.01;
  m.cogging = 5e-3;
  m.coggingPerTurn = 168;
  m.thermalCapacity = 60.0;
  m.thermalResistance = 4.0;
  m.ratedCurrent = 20.0;
  return m;
}

MotorParams hobby2204() {
  MotorParams m;
  m.name = "hobby 2204";
  m.resistance = 0.07;
  m.inductanceD = m.inductanceQ = 12e-6;
  m.fluxLinkage = 3.42e-4;
  m.polePairs = 7;
  m.inertia = 3e-6;
  m.viscous = 1e-7;
  m.coulomb = 5e-4;
  m.cogging = 1e-3;
  m.coggingPerTurn = 84;
  m.thermalCapacity = 8.0;
  m.thermalResistance = 12.0;
  m.ratedCurrent = 10.0;
  return m;
}

}  // namespace motors

}  // namespace sim
