#pragma once
// -----------------------------------------------------------------------------
// The board around the motor, as the firmware sees it: one Sample per PWM
// period in, one Output per period back (docs/07-firmware.md §7.7).
//
//   sense     shunt × CSA gain → 12-bit code: offset, noise, and a garbage
//             reading when the low-side window before the valley was shorter
//             than the CSA settling time
//   encoder   MT6835-like: 21-bit, read at the PWM peak (half a period before
//             the current sample), noise, eccentricity, mounting offset;
//             magnet loss and slip can be injected
//   driver    DRV8353 VDS over-current: latched shutdown (nFAULT, bridge off
//             in hardware) until CLR_FLT; VM undervoltage lockout
//   timing    duties written at tick k are active over [t_k+1, t_k+2]
//             (TIM1 preload), exactly the pipeline the firmware compensates
//   slow      FET and motor NTC codes for the main loop's ADC reads
//
// Usage per tick: `out = firmware.tick(bench.sample()); bench.step(out);`
// -----------------------------------------------------------------------------
#include <random>

#include "foc/FocCore.h"
#include "sim/Motor.h"

namespace sim {

struct BenchConfig {
  double pwmPeriod = 1.0 / 30000.0;
  int substeps = 32;  // RK4 steps per PWM period
  InverterParams inverter{};
  SupplyParams supply{};
  ThermalParams thermal{};
  // Current sense (board/Board.h): SO = VREF/2 + G·R_shunt·i.
  double csaGain = 10.0;
  double vref = 3.3;
  double csaOffsetVolts[3] = {0.004, -0.003, 0.002};  // residual after the DRV's own calibration
  double csaNoiseCounts = 1.5;                         // rms
  double csaSettling = 0.8e-6;                         // s of low-side time needed before the sample
  double busDivider = 5.1 / 105.1;
  // Driver.
  double vdsLevel = 0.6;        // V across a FET that trips the VDS over-current shutdown
  double undervoltage = 6.0;    // V: VM lockout
  // Encoder.
  int encoderBits = 21;
  int encoderDirection = 1;       // counts vs mechanical angle
  double encoderOffset = 0.3141;  // turns: magnet orientation, unknown to the firmware
  double encoderNoiseCounts = 3.0;
  double eccentricity = 0.0;      // turns, first harmonic
  // Thermistors: 10k B3434 to GND, 10k pull-up to the ADC reference.
  double ntcR25 = 10000.0, ntcBeta = 3434.0, ntcPullup = 10000.0;
  uint32_t seed = 1;
};

class Bench {
 public:
  Bench(const MotorParams& motor, const BenchConfig& cfg = BenchConfig{});

  foc::Sample sample();
  void step(const foc::Output& out);

  // Main-loop reads.
  uint16_t fetNtcCode();
  uint16_t motorNtcCode();
  bool driverFault() const { return driverLatched_ || undervoltage_; }  // nFAULT low

  // Fault injection and the driver's own controls.
  void clearDriverFault() { driverLatched_ = false; }  // DRV8353 CLR_FLT over SPI
  void setMagnet(bool present) { magnet_ = present; }
  bool magnet() const { return magnet_; }
  void slipEncoder(double turns) { cfg_.encoderOffset += turns; }
  BenchConfig& config() { return cfg_; }
  const BenchConfig& config() const { return cfg_; }

  // Firmware constants that match this bench (what board/Board.h holds for the real one).
  float ampsPerCount() const;
  float busVoltsPerCount() const;

  Motor& motor() { return motor_; }
  const Motor& motor() const { return motor_; }
  double time() const { return time_; }
  uint64_t ticks() const { return ticks_; }
  bool bridgeEnabled() const { return activeEnable_ && !driverFault(); }
  const double* duties() const { return active_; }

 private:
  uint16_t senseCode(double amps, int phase, bool settled);
  uint32_t encoderRead(double mechanicalAngle);
  uint16_t ntcCode(double celsius);
  void checkDriver();

  BenchConfig cfg_;
  Motor motor_;
  std::mt19937 rng_;
  std::normal_distribution<double> gauss_{0.0, 1.0};
  double time_ = 0.0;
  uint64_t ticks_ = 0;
  // Duties active now (written last tick), and those active over the interval that ended at
  // the current sample (decide whether each CSA had time to settle).
  double active_[3] = {0.5, 0.5, 0.5};
  bool activeEnable_ = false;
  double windowDuty_[3] = {0.5, 0.5, 0.5};
  bool windowEnable_ = false;
  uint32_t encoderAtPeak_ = 0;
  bool encoderValid_ = true;
  bool magnet_ = true;
  bool driverLatched_ = false, undervoltage_ = false;
};

}  // namespace sim
