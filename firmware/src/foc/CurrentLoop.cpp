#include "foc/CurrentLoop.h"

using foc::Dq;

CurrentLoop::Gains CurrentLoop::forMotor(float resistance, float inductance, float hz) {
  const float wc = foc::kTwoPi * hz;
  return {inductance * wc, resistance * wc};
}

namespace {

// One axis: returns the limited output and updates the integral.
float axis(float error, float ff, float limit, const CurrentLoop::Gains& g, float dt, float& integral,
           bool& saturated) {
  const float candidate = foc::clamp(integral + g.ki * dt * error, -limit, limit);
  const float v = ff + g.kp * error + candidate;
  const float out = foc::clamp(v, -limit, limit);
  if (out != v) {
    saturated = true;
    // Integrate only if that moves the output back towards the limit's inside.
    if ((v > 0.0f) != (error > 0.0f)) integral = candidate;
  } else {
    integral = candidate;
  }
  return out;
}

}  // namespace

Dq CurrentLoop::update(Dq reference, Dq measured, Dq feedForward, float vmax, float dt) {
  saturated_ = false;
  const float vd = axis(reference.d - measured.d, feedForward.d, vmax, gains_, dt, integral_.d, saturated_);
  const float qLimit = std::sqrt(std::fmax(vmax * vmax - vd * vd, 0.0f));
  const float vq = axis(reference.q - measured.q, feedForward.q, qLimit, gains_, dt, integral_.q, saturated_);
  return {vd, vq};
}
