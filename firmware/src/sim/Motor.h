#pragma once
// -----------------------------------------------------------------------------
// Host-only plant model (docs/07-firmware.md §7.7): a PMSM in the rotor (dq)
// frame, driven through an average-value inverter with dead time, fed from a
// supply through the board's bus capacitance, plus lumped thermal models of
// the board and the motor. double precision; never built for the MCU.
//
//   L_d·did/dt = v_d − R(T)·i_d + ω_e·L_q·i_q
//   L_q·diq/dt = v_q − R(T)·i_q − ω_e·(L_d·i_d + λ)
//   J·dω/dt    = 1.5·p·(λ·i_q + (L_d − L_q)·i_d·i_q) − B·ω − T_c·sgn(ω) − cogging − load
//   C·dV/dt    = i_supply − Σ d_x·i_x − i_logic
//
// Phase-node voltage of each leg, averaged over a PWM period:
//   u_x = d_x·V_bus − sgn(i_x)·(t_dead/T)·V_bus − R_leg(T)·i_x
// with sgn smoothed over ±0.2 A (the node's slow transition at low current).
// The neutral floats, so the common mode of u_a, u_b, u_c does not reach the
// windings. A bench supply cannot sink current and limits its output; a
// battery takes regenerated current back.
//
// Not modelled: diode rectification with the bridge off (a coasting motor
// whose back-EMF exceeds V_bus pumps the bus on real hardware), saturation,
// iron losses.
// -----------------------------------------------------------------------------
#include <cstdint>

namespace sim {

struct MotorParams {
  const char* name = "motor";
  double resistance = 0.1;    // Ω, phase (line-to-neutral) at 25 °C
  double inductanceD = 40e-6; // H
  double inductanceQ = 40e-6; // H
  double fluxLinkage = 1e-3;  // Wb, peak per phase
  int polePairs = 7;
  double inertia = 1e-4;      // kg·m²
  double viscous = 1e-5;      // N·m·s/rad
  double coulomb = 1e-3;      // N·m
  double cogging = 0.0;       // N·m amplitude
  int coggingPerTurn = 84;    // cogging cycles per mechanical turn
  double thermalCapacity = 60.0;  // J/K, winding + stator
  double thermalResistance = 4.0; // K/W to ambient
  double ratedCurrent = 10.0;     // A peak, for the UI's scales

  double torqueConstant() const { return 1.5 * polePairs * fluxLinkage; }  // N·m/A (q axis)
};

struct InverterParams {
  double deadTime = 200e-9;     // s
  double fetResistance = 3e-3;  // Ω at 25 °C (BSC030N08NS5), rises 0.6 %/K
  double shunt = 1e-3;          // Ω
  double switchingTime = 25e-9; // s of V·I overlap per period and leg
  double logicPower = 0.35;     // W: gate drive, buck, MCU, CAN
};

struct SupplyParams {
  enum class Kind : uint8_t { Bench, Battery };
  Kind kind = Kind::Bench;
  double volts = 24.0;
  double currentLimit = 5.0;    // A (bench supply constant-current limit)
  double resistance = 0.05;     // Ω: leads and source
  double capacitance = 60e-6;   // F on the board: MLCCs at DC bias plus the 22 µF can
  double logicCurrent = 0.03;   // A: the board's own draw (approximately constant)
  bool connected = true;
};

struct ThermalParams {
  double ambient = 25.0;           // °C
  double boardCapacity = 10.0;     // J/K
  double boardResistance = 15.0;   // K/W to ambient, uncooled
};

class Motor {
 public:
  enum class Mechanics : uint8_t {
    Free,    // the rotor follows torque, friction, cogging and load
    Locked,  // held at its angle (locked-rotor tests)
    Speed,   // driven at a fixed speed (dyno)
  };

  Motor(const MotorParams& m, const InverterParams& inv, const SupplyParams& sup, const ThermalParams& th);

  // Advance by dt with the leg duties held (enabled = false: bridge off, windings open).
  void step(const double duty[3], bool enabled, double pwmPeriod, double dt, int substeps);

  void setMechanics(Mechanics mode, double speed = 0.0);
  Mechanics mechanics() const { return mechanics_; }
  void setLoad(double torque) { load_ = torque; }
  void setExtraInertia(double j) { extraInertia_ = j; }
  void setBrake(double viscous) { brake_ = viscous; }
  void setAngle(double radians) { theta_ = radians; }
  SupplyParams& supply() { return sup_; }
  ThermalParams& thermal() { return th_; }

  double angle() const { return theta_; }     // mechanical rad, continuous
  double velocity() const { return omega_; }  // mechanical rad/s
  double id() const { return id_; }
  double iq() const { return iq_; }
  double busVoltage() const { return vbus_; }
  double supplyCurrent() const { return supplyCurrent_; }
  double boardTemperature() const { return boardT_; }
  double motorTemperature() const { return motorT_; }
  double resistance() const;  // winding, at its temperature
  double legResistance() const;
  void phaseCurrents(double out[3]) const;
  double torque() const;  // electromagnetic, N·m
  double lossPower() const { return boardLoss_ + motorLoss_; }
  const MotorParams& params() const { return m_; }

 private:
  struct State {
    double id, iq, omega, theta, vbus;
  };
  State derivative(const State& s, const double* duty) const;
  double supplyCurrentAt(double vbus) const;

  MotorParams m_;
  InverterParams inv_;
  SupplyParams sup_;
  ThermalParams th_;
  Mechanics mechanics_ = Mechanics::Free;
  double load_ = 0.0, extraInertia_ = 0.0, brake_ = 0.0;
  double id_ = 0.0, iq_ = 0.0, omega_ = 0.0, theta_ = 0.0, vbus_ = 0.0;
  double boardT_ = 25.0, motorT_ = 25.0;
  double supplyCurrent_ = 0.0, boardLoss_ = 0.0, motorLoss_ = 0.0;
  double pwmPeriod_ = 1.0 / 30000.0;  // for the dead-time term inside derivative()
};

// The seeded test set (docs/07-firmware.md §7.7 test 4): phase values.
namespace motors {
// GBM2804-class gimbal motor, 12N14P, ~150 rpm/V.
MotorParams gimbal();
// 5010-class quasi-direct-drive motor, 24N28P, ~360 rpm/V, with a light gearbox's friction.
MotorParams qdd5010();
// 2204 hobby motor, 12N14P, ~2300 rpm/V: tiny L, low flux, fast.
MotorParams hobby2204();
}  // namespace motors

}  // namespace sim
