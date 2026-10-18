#pragma once
// -----------------------------------------------------------------------------
// The current loop: everything that runs in the ADC interrupt, once per PWM
// period (docs/07-firmware.md §7.2).
//
//   CSA codes ─► amps ─► Clarke ─► Park ─► PI + decoupling ─► inverse Park ─► SVPWM ─► duties
//   encoder raw ─► tracker (multi-turn count, velocity) ─► electrical angle + latency compensation
//
// No HAL in here. On the MCU the ADC interrupt hands in a Sample and writes
// the Output to TIM1; on the host the simulator (sim/Bench.h) does the same
// with a motor model, so this exact code is what the tests exercise.
//
// Timing, per tick k (docs/04-architecture.md §4.3):
//   t_k            ADC samples the phase currents at the PWM valley
//   t_k − ½T       the encoder was read (SPI started at the counter peak)
//   t_k+1 … t_k+2  the duties written now are active (TIM1 preload)
// so currents are Park-transformed at θ(t_k) and the output vector is placed
// at θ(t_k + 1.5T), its mid-point.
//
// The main loop and the 1 kHz procedures command it through the setters and
// read takeAverages(); on the MCU they do so with the control interrupt
// masked (a few hundred nanoseconds), as the S1's MotionCore.
// -----------------------------------------------------------------------------
#include "control/EncoderTracker.h"
#include "foc/CurrentLoop.h"
#include "foc/Math.h"
#include "foc/Svpwm.h"

namespace foc {

// One conversion set, taken at the PWM valley (all low-side FETs on).
struct Sample {
  uint16_t current[3];  // CSA codes, phases A, B, C (12-bit)
  uint16_t bus;         // V_BUS divider code
  uint32_t encoder;     // single-turn count, encoderBits wide
  bool encoderFresh;    // a new encoder result since the last tick
};

// For TIM1 CCR1..3 (preloaded: active from the next valley).
struct Output {
  Duty3 duty;
  bool enable;  // false: all six FETs off
};

// Means over the ticks since the last takeAverages() (procedures, telemetry).
struct Averages {
  uint32_t ticks = 0;
  float code[3] = {0.0f, 0.0f, 0.0f};  // raw CSA codes (offset calibration)
  Abc i{0.0f, 0.0f, 0.0f};
  Dq idq{0.0f, 0.0f};
  Dq vdq{0.0f, 0.0f};  // applied (after limiting)
  float vbus = 0.0f;
  float omega = 0.0f;  // electrical rad/s, from the encoder
  // Inductance test, per tick: s = sign of the square wave that acted on Δi,
  // m = mean current over that tick, Δ = current change. Sums, not means.
  float sumS = 0.0f, sumM = 0.0f, sumD = 0.0f;
  float sumSD = 0.0f, sumMD = 0.0f, sumSM = 0.0f, sumMM = 0.0f;
  uint32_t inductanceTicks = 0;
};

class FocCore {
 public:
  enum class Drive : uint8_t {
    Off,         // bridge off
    Voltage,     // fixed vd, vq, open loop
    Current,     // id, iq through the current loop
    Inductance,  // vd = offset ± V, alternating every `halfPeriod` ticks (winding inductance test)
  };
  enum class AngleSource : uint8_t {
    Encoder,    // field oriented: the rotor angle from the encoder
    Commanded,  // a set angle, optionally rotating (calibration)
  };

  // Latched faults: the bridge stays off until clearFaults().
  static constexpr uint16_t kFaultOvercurrent = 1u << 0;
  static constexpr uint16_t kFaultEncoder = 1u << 1;  // no fresh sample for too long
  static constexpr uint16_t kFaultOvervoltage = 1u << 2;
  static constexpr uint16_t kFaultUndervoltage = 1u << 3;

  struct Config {
    float tickPeriod = 1.0f / 30000.0f;  // s: one PWM period = one current-loop tick
    // Sensing (values from board/Board.h): signed amps per CSA count, volts per V_BUS count.
    float ampsPerCount = 0.0f;
    float busVoltsPerCount = 0.0f;
    float currentOffset[3] = {2048.0f, 2048.0f, 2048.0f};  // CSA codes at zero current (calibrated)
    float sampleWindow = 1.0e-6f;  // s of low-side on-time the CSA needs before the valley sample
    // Encoder → electrical angle: θe = encoderDirection · polePairs · raw + encoderOffset.
    uint8_t encoderBits = 21;
    int8_t encoderDirection = 1;
    uint8_t polePairs = 7;
    Angle encoderOffset = 0;
    float velocityBandwidth = 2000.0f;  // rad/s, encoder tracking PLL
    uint16_t encoderTimeout = 30;       // ticks without a fresh sample → fault (encoder angle only)
    float encoderLead = 0.5f;           // ticks between the encoder read and the current sample
    float outputDelay = 1.5f;           // ticks from the current sample to the output's mid-point
    // The motor (identified by calibration): decoupling feed-forward, regen limit.
    float resistance = 0.0f;   // Ω, phase, bridge included
    float inductanceD = 0.0f;  // H
    float inductanceQ = 0.0f;  // H
    float fluxLinkage = 0.0f;  // Wb, peak per phase
    bool decoupling = true;
    CurrentLoop::Gains currentGains{};
    // Limits.
    float maxCurrent = 10.0f;       // A, |i_dq| reference clamp
    float overcurrentTrip = 20.0f;  // A, any phase sample → fault
    float maxModulation = 0.95f;    // fraction of V_bus/√3
    float busOvervoltage = 58.0f;   // V
    float busUndervoltage = 8.0f;   // V, checked while the bridge is on
  };

  void configure(const Config& c);
  Config& config() { return config_; }
  const Config& config() const { return config_; }

  // ---- Real time ---------------------------------------------------------------------------------------
  Output tick(const Sample& s);

  // ---- Commands ----------------------------------------------------------------------------------------
  void setDrive(Drive d);
  void setAngleSource(AngleSource a) { angleSource_ = a; }
  void setVoltage(Dq v) { voltageRef_ = v; }
  void setCurrent(Dq i) { currentRef_ = i; }
  void setCommandedAngle(Angle a, float omega);  // omega: electrical rad/s it then rotates at
  void setInductanceTest(float offsetVolts, float volts, uint16_t halfPeriod);
  void clearFaults() { faults_ = 0; }

  // ---- State -------------------------------------------------------------------------------------------
  Drive drive() const { return drive_; }
  uint16_t faults() const { return faults_; }
  Averages takeAverages();
  Dq current() const { return idq_; }
  Dq voltage() const { return vdq_; }
  Abc phaseCurrents() const { return iabc_; }
  float busVoltage() const { return vbus_; }
  Angle angle() const { return angle_; }            // electrical, at the current sample
  float electricalVelocity() const { return omega_; }  // rad/s, from the encoder
  Angle commandedAngle() const { return angleCmd_; }
  const EncoderTracker& encoder() const { return tracker_; }
  // Electrical angle of an encoder count, before the offset is added.
  Angle electricalFromRaw(uint32_t raw) const;

 private:
  Config config_{};
  EncoderTracker tracker_;
  CurrentLoop loop_;
  bool trackerStarted_ = false;

  Drive drive_ = Drive::Off;
  AngleSource angleSource_ = AngleSource::Encoder;
  Dq voltageRef_{0.0f, 0.0f};
  Dq currentRef_{0.0f, 0.0f};
  Dq predicted_{0.0f, 0.0f};  // modelled closed-loop current, for decoupling
  Angle angleCmd_ = 0;
  int32_t angleStep_ = 0;  // per tick
  float omegaCmd_ = 0.0f;
  float testOffset_ = 0.0f;
  float testVolts_ = 0.0f;
  uint16_t testHalfPeriod_ = 1;
  uint16_t testCount_ = 0;
  float testSign_ = 1.0f;

  uint16_t faults_ = 0;
  uint8_t overvoltageTicks_ = 0;

  // Output history: [0] written last tick (active now), [1] the tick before (active
  // over the interval that ended at this sample).
  Duty3 dutyHistory_[2] = {{0.5f, 0.5f, 0.5f}, {0.5f, 0.5f, 0.5f}};
  bool enableHistory_[2] = {false, false};
  float signHistory_[2] = {0.0f, 0.0f};  // inductance test sign, same pipeline
  float previousId_ = 0.0f;

  Abc iabc_{0.0f, 0.0f, 0.0f};
  Dq idq_{0.0f, 0.0f};
  Dq vdq_{0.0f, 0.0f};
  float vbus_ = 0.0f;
  Angle angle_ = 0;
  float omega_ = 0.0f;
  Averages acc_{};
};

}  // namespace foc
