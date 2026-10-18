#pragma once
// -----------------------------------------------------------------------------
// Motor calibration and identification (docs/07-firmware.md §7.6): a
// non-blocking state machine stepped at 1 kHz from the main loop, as the S1's
// procedures. Each stage writes what it found into the FocCore's config, so
// the next one can use it:
//
//   1. Offsets      bridge off, CSA zero codes averaged over 0.5 s
//   2. Resistance   d-axis voltage at θ = 0, regulated slowly to ½·I and I;
//                   R = ΔV/ΔI, which cancels the dead-time voltage
//   3. Inductance   d-axis square wave on top of a DC current, so the current
//                   never crosses zero and the dead-time voltage stays
//                   constant; Δi per tick regressed on the square wave, the
//                   current (R) and a constant (DC voltage, dead time).
//                   Current-loop gains from R and L
//   4. Pole pairs   current vector rotated N electrical turns: pole pairs =
//                   N / mechanical turns, direction from the sign
//   5. Encoder      the vector swept backward then forward; the circular mean
//      offset       of (commanded − encoder) angle, so friction lag cancels
//   6. Flux         q-axis voltage on the encoder angle (the motor regulates
//      linkage      its own speed by back-EMF), two speeds:
//                   λ = Δ(v_q − R·i_q − ω·L·i_d) / Δω
//
// The procedure owns the core's drive while it runs and leaves it Off.
// Double precision only in the accumulators (main loop, 1 kHz).
// -----------------------------------------------------------------------------
#include "foc/FocCore.h"

class Calibration {
 public:
  enum class Phase : uint8_t { Idle, Offsets, Resistance, Inductance, PolePairs, EncoderOffset, FluxLinkage, Done, Failed };
  enum class Error : uint8_t {
    None,
    Fault,        // the core latched a fault
    Aborted,
    NoCurrent,    // the voltage limit was reached first: open phase or R too high
    Resistance,   // R out of range
    Inductance,   // L out of range
    NoMotion,     // the encoder did not move with the field: magnet, wiring or load
    PolePairs,    // N electrical turns did not match a whole number of pole pairs
    EncoderNoise, // the offset samples did not agree
    Flux,         // the motor did not reach speed for the flux test
  };

  struct Settings {
    float current = 2.0f;           // A, calibration current (rotor lock, R test level)
    float maxVoltage = 8.0f;        // V, open-loop limit for the R test
    float bandwidth = 1500.0f;      // Hz, current-loop target
    float scanSpeed = 12.566371f;   // electrical rad/s for the encoder scans (2 turns/s)
    float poleScanTurns = 8.0f;     // electrical turns for the pole-pair count
    float offsetScanTurns = 4.0f;   // electrical turns each way for the offset
    float fluxEmf = 3.0f;           // V of back-EMF to reach in the flux test
    float fluxMaxSpeed = 200.0f;    // mechanical rad/s cap for the flux test
    bool flux = true;               // run step 6
  };

  struct Result {
    float offset[3] = {0.0f, 0.0f, 0.0f};  // CSA zero codes
    float resistance = 0.0f;               // Ω, phase, bridge included
    float inductance = 0.0f;               // H
    uint8_t polePairs = 0;
    int8_t direction = 0;                  // encoder counts vs electrical rotation
    foc::Angle encoderOffset = 0;
    float offsetSpread = 0.0f;             // 1 − mean resultant length of the offset samples
    float fluxLinkage = 0.0f;              // Wb
    float torqueConstant() const { return 1.5f * static_cast<float>(polePairs) * fluxLinkage; }
  };

  void start(foc::FocCore& core, const Settings& s);
  void abort(foc::FocCore& core);
  // Once per millisecond.
  void update(foc::FocCore& core);

  Phase phase() const { return phase_; }
  Error error() const { return error_; }
  bool running() const { return phase_ != Phase::Idle && phase_ != Phase::Done && phase_ != Phase::Failed; }
  const Result& result() const { return result_; }

 private:
  void enter(foc::FocCore& core, Phase p);
  void fail(foc::FocCore& core, Error e);
  void updateOffsets(foc::FocCore& core, const foc::Averages& a);
  void updateResistance(foc::FocCore& core, const foc::Averages& a);
  void updateInductance(foc::FocCore& core, const foc::Averages& a);
  void updatePolePairs(foc::FocCore& core, const foc::Averages& a);
  void updateEncoderOffset(foc::FocCore& core, const foc::Averages& a);
  void updateFlux(foc::FocCore& core, const foc::Averages& a);
  void clearSums();

  Settings settings_{};
  Result result_{};
  Phase phase_ = Phase::Idle;
  Error error_ = Error::None;
  uint32_t ms_ = 0;   // in the current sub-step
  uint8_t sub_ = 0;
  float volts_ = 0.0f;
  float resistanceEstimate_ = 0.0f;
  float resistanceIntercept_ = 0.0f;  // V at zero current from the R test: the dead-time voltage
  float testOffset_ = 0.0f;
  float testVolts_ = 0.0f;
  uint16_t halfPeriod_ = 1;
  int64_t startCounts_ = 0;
  uint32_t scanMs_ = 0;
  double sum_[10] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  double weight_ = 0.0;
  double point_[2][4] = {{0, 0, 0, 0}, {0, 0, 0, 0}};  // flux test: vq − R·iq, ω, L·id·ω
};
