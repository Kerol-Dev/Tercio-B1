#pragma once
// -----------------------------------------------------------------------------
// The B1 joint: the firmware's application, minus the hardware.
//
//   tick()     ADC interrupt, once per PWM period: every `outerDivider` ticks
//              the S1 planner and the outer loop make a torque, which becomes
//              the i_q reference (regen-clamped); then the FocCore runs
//   update()   main loop, 1 kHz: calibration, deadman, temperatures and
//              derating, fault policy, state transitions
//
// The MCU's main.cpp wires these to TIM1/ADC/SPI; the simulator
// (src/simulator) wires them to sim::Bench. The CAN layer (app/Node, F4)
// will map protocol commands onto the command methods.
//
// Frames: positions and velocities are rotor turns in the motor frame
// (positive = positive electrical rotation), absolute within the first turn
// at power-up since the MT6835 is absolute.
// -----------------------------------------------------------------------------
#include "control/Fixed.h"
#include "control/OuterLoop.h"
#include "control/Trajectory.h"
#include "foc/Calibration.h"
#include "foc/FocCore.h"

class Joint {
 public:
  // AxisState numbering of protocol v2 (docs/07-firmware.md §7.4).
  enum class State : uint8_t {
    Disabled = 0,
    Holding = 1,
    Moving = 2,
    Velocity = 3,
    Calibrating = 5,
    Fault = 8,
    Torque = 9,
    Impedance = 10,
  };

  // Fault bits: the S1's meanings plus the B1 range 9–14 (docs/07-firmware.md §7.5).
  struct Fault {
    static constexpr uint16_t kOverTemperature = 1u << 0;  // FET / board
    static constexpr uint16_t kDriverFault = 1u << 2;      // DRV8353 nFAULT (VDS OCP, UVLO, …)
    static constexpr uint16_t kEncoder = 1u << 4;
    static constexpr uint16_t kCalibrationFailed = 1u << 6;
    static constexpr uint16_t kCommandTimeout = 1u << 8;
    static constexpr uint16_t kOverVoltage = 1u << 9;
    static constexpr uint16_t kUnderVoltage = 1u << 10;
    static constexpr uint16_t kOverCurrent = 1u << 11;
    static constexpr uint16_t kMotorOverTemperature = 1u << 12;
    // Faults that switch the bridge off; the rest stop and hold.
    static constexpr uint16_t kHardMask = kOverTemperature | kDriverFault | kEncoder | kOverVoltage | kUnderVoltage |
                                          kOverCurrent | kMotorOverTemperature;
  };
  struct Warning {
    static constexpr uint16_t kTemperatureHigh = 1u << 0;  // derating
    static constexpr uint16_t kRegenLimited = 1u << 8;     // braking torque clamped by the bus
    static constexpr uint16_t kNotCalibrated = 1u << 9;
  };

  struct Settings {
    foc::FocCore::Config foc{};
    OuterLoop::Gains gains{};
    float maxVelocity = 30.0f;       // turns/s
    float maxAcceleration = 200.0f;  // turns/s²
    float commandTimeout = 1.0f;     // s; velocity, torque and impedance stop without fresh commands (0: off)
    float followingWindow = 0.05f;   // turns: velocity mode drags its reference along beyond this
    float maxRegenCurrent = 0.5f;    // A back into the supply
    float regenHeadroom = 3.0f;      // V above the bus at enable over which regen fades to zero
    float fetDerateStart = 80.0f;    // °C
    float fetOverTemperature = 100.0f;
    bool motorNtc = false;
    float motorDerateStart = 100.0f;
    float motorOverTemperature = 120.0f;
    // Thermistors (board/Board.h): NTC to GND, pull-up to the ADC reference.
    float ntcR25 = 10000.0f, ntcBeta = 3434.0f, ntcPullup = 10000.0f;
    uint8_t outerDivider = 2;
  };

  // Slow inputs, read by the main loop (ADC regular group, GPIO).
  struct SlowSample {
    uint16_t fetNtc = 2048;
    uint16_t motorNtc = 2048;
    bool driverFault = false;  // nFAULT low
  };

  struct Telemetry {
    State state = State::Disabled;
    uint16_t faults = 0, warnings = 0;
    double position = 0.0;  // turns
    float velocity = 0.0f;  // turns/s
    double target = 0.0;    // turns: planner position (or impedance target)
    float targetVelocity = 0.0f;
    float torque = 0.0f, torqueRef = 0.0f;  // N·m
    foc::Dq idq{0, 0}, idqRef{0, 0}, vdq{0, 0};
    float vbus = 0.0f, ibus = 0.0f;
    float fetTemperature = 0.0f, motorTemperature = 0.0f;
    float derate = 1.0f;
    Calibration::Phase calibration = Calibration::Phase::Idle;
  };

  void configure(const Settings& s);
  Settings& settings() { return settings_; }

  foc::Output tick(const foc::Sample& s);
  void update(const SlowSample& s);

  // ---- Commands (false: refused in this state) -----------------------------------------------------------
  bool enable();
  void disable();
  void stop();  // decelerate and hold
  bool moveTo(double turns, float maxVelocity, float maxAcceleration);
  bool setVelocity(float turnsPerSecond, float maxAcceleration);
  bool setTorque(float newtonMetres, float maxVelocity);
  bool impedance(double position, float velocity, float kp, float kd, float torque);
  bool calibrate(const Calibration::Settings& s);
  void clearFaults();
  void heartbeat() { commandAgeMs_ = 0; }
  void setGains(const OuterLoop::Gains& g) {
    settings_.gains = g;
    outer_.setGains(g);
  }

  // ---- State ----------------------------------------------------------------------------------------------
  State state() const { return state_; }
  uint16_t faults() const { return faults_; }
  bool calibrated() const { return calibrated_; }
  void setCalibrated(bool c) { calibrated_ = c; }  // after loading a stored calibration
  float torqueConstant() const;
  Telemetry telemetry() const;
  const Calibration& calibration() const { return calibration_; }
  const foc::FocCore& core() const { return core_; }

 private:
  q32::Pos position() const;
  float velocity() const;  // turns/s
  void enterHold();
  void raise(uint16_t fault);
  float regenLimitedCurrent(float iq);
  float ntcCelsius(uint16_t code) const;

  Settings settings_{};
  foc::FocCore core_;
  OuterLoop outer_;
  Trajectory trajectory_;
  Calibration calibration_;

  State state_ = State::Disabled;
  uint16_t faults_ = 0;
  uint16_t warnings_ = 0;
  bool calibrated_ = false;
  uint32_t ticks_ = 0;
  uint32_t commandAgeMs_ = 0;
  uint32_t offsetsTracked_ = 0;  // ms with the bridge off (the first 20 are skipped: currents decay)

  float torqueCmd_ = 0.0f, torqueVelocityLimit_ = 0.0f;
  q32::Pos impPosition_ = 0;
  float impVelocity_ = 0.0f, impKp_ = 0.0f, impKd_ = 0.0f, impTorque_ = 0.0f;
  float torqueRef_ = 0.0f;
  float derate_ = 1.0f;
  float regenStart_ = 0.0f;  // V
  bool regenLimited_ = false;  // set by tick(), reported and cleared by update()
  float fetTemperature_ = 25.0f, motorTemperature_ = 25.0f;
};
