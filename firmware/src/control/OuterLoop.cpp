#include "control/OuterLoop.h"

#include <cmath>

namespace {
float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
}  // namespace

float OuterLoop::update(Mode mode, const Reference& ref, q32::Pos position, float velocity, float maxTorque,
                        float maxVelocity, float dt) {
  return update(mode, ref, position, velocity, maxTorque, maxVelocity, dt, gains_.kp, gains_.kd);
}

float OuterLoop::update(Mode mode, const Reference& ref, q32::Pos position, float velocity, float maxTorque,
                        float maxVelocity, float dt, float kp, float kd) {
  const Gains& g = gains_;
  float torque = 0.0f, error = 0.0f, ki = 0.0f;
  switch (mode) {
    case Mode::Torque:
      torque = ref.torque;
      // Past the speed limit, a velocity loop on the limit takes over (it can only brake).
      if (velocity > maxVelocity) torque = std::fmin(torque, g.kv * (maxVelocity - velocity));
      if (velocity < -maxVelocity) torque = std::fmax(torque, g.kv * (-maxVelocity - velocity));
      integral_ = 0.0f;
      break;
    case Mode::Velocity: {
      const float target = clampf(ref.velocity, -maxVelocity, maxVelocity);
      error = target - velocity;
      ki = g.kvi;
      torque = g.kv * error + integral_ + ref.torque;
      break;
    }
    case Mode::Position:
      error = q32::diff(ref.position, position);
      ki = g.ki;
      torque = kp * error + kd * (ref.velocity - velocity) + integral_ + ref.torque;
      break;
  }
  const float out = clampf(torque, -maxTorque, maxTorque);
  saturated_ = out != torque;
  // Integrate unless that would push further into saturation.
  if (ki != 0.0f && !(saturated_ && (torque > 0.0f) == (error > 0.0f))) {
    integral_ = clampf(integral_ + ki * error * dt, -g.integralLimit, g.integralLimit);
  }
  return out;
}
