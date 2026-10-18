#pragma once
// -----------------------------------------------------------------------------
// Position, velocity and impedance loops on top of the current loop
// (docs/07-firmware.md §7.4). Everything is in the motor frame: turns of the
// rotor, positive with positive electrical rotation. Output is a torque.
//
//   Position, impedance:  τ = kp·(p* − p) + kd·(v* − v) + ki·∫(p* − p) + τ_ff
//   Velocity:             τ = kv·(v* − v) + kvi·∫(v* − v) + τ_ff
//   Torque:               τ = τ_ff, pulled back by kv beyond ±maxVelocity
//
// Units: turns, turns/s, N·m. kp N·m/turn, kd and kv N·m/(turn/s), ki N·m/(turn·s),
// kvi N·m/turn. The integrators are clamped to ±integralLimit (N·m) and
// frozen while the output saturates.
// -----------------------------------------------------------------------------
#include "control/Fixed.h"

class OuterLoop {
 public:
  enum class Mode : uint8_t { Torque, Velocity, Position };

  struct Gains {
    float kp = 2.0f;
    float kd = 0.05f;
    float ki = 0.0f;
    float kv = 0.05f;
    float kvi = 0.5f;
    float integralLimit = 0.2f;  // N·m
  };

  struct Reference {
    q32::Pos position = 0;
    float velocity = 0.0f;  // turns/s
    float torque = 0.0f;    // N·m feed-forward (torque command in Torque mode)
  };

  void setGains(const Gains& g) { gains_ = g; }
  const Gains& gains() const { return gains_; }
  void reset() { integral_ = 0.0f; }

  // `kp`, `kd` override the position gains (impedance mode passes the commanded ones).
  float update(Mode mode, const Reference& ref, q32::Pos position, float velocity, float maxTorque,
               float maxVelocity, float dt);
  float update(Mode mode, const Reference& ref, q32::Pos position, float velocity, float maxTorque,
               float maxVelocity, float dt, float kp, float kd);

  bool saturated() const { return saturated_; }

 private:
  Gains gains_{};
  float integral_ = 0.0f;
  bool saturated_ = false;
};
