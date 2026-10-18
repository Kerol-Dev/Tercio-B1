#pragma once
// -----------------------------------------------------------------------------
// d/q current controller: two PI loops plus feed-forward, limited to the
// voltage circle the bridge can produce.
//
//   v = ff + kp·e + ∫ki·e
//
// Gains from the motor (docs/07-firmware.md §7.6 step 8): kp = L·ωc,
// ki = R·ωc puts the PI zero on the winding's pole, so the open loop is
// ωc/s and the closed loop a first-order lag at ωc (minus the PWM delay).
//
// Voltage limit: d first (it holds the field and the decoupling term), q gets
// what is left of the circle. A saturated axis stops integrating in the
// direction that would wind it up further (conditional integration).
// -----------------------------------------------------------------------------
#include "foc/Math.h"

class CurrentLoop {
 public:
  struct Gains {
    float kp = 0.0f;  // V/A
    float ki = 0.0f;  // V/(A·s)
  };

  // Gains for a closed-loop bandwidth of `hz` on a winding of R (Ω) and L (H).
  static Gains forMotor(float resistance, float inductance, float hz);

  void setGains(const Gains& g) { gains_ = g; }
  const Gains& gains() const { return gains_; }
  void reset() { integral_ = {0.0f, 0.0f}; saturated_ = false; }

  foc::Dq update(foc::Dq reference, foc::Dq measured, foc::Dq feedForward, float vmax, float dt);

  foc::Dq integral() const { return integral_; }
  bool saturated() const { return saturated_; }

 private:
  Gains gains_{};
  foc::Dq integral_{0.0f, 0.0f};
  bool saturated_ = false;
};
