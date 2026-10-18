#include "foc/Svpwm.h"

namespace foc {

Duty3 svpwm(AlphaBeta v, float vbus) {
  if (!(vbus > 0.0f)) return {0.5f, 0.5f, 0.5f};
  const float limit = linearLimit(vbus);
  const float m2 = v.alpha * v.alpha + v.beta * v.beta;
  if (m2 > limit * limit) {
    const float k = limit / std::sqrt(m2);
    v.alpha *= k;
    v.beta *= k;
  }
  const Abc p = inverseClarke(v);
  const float hi = std::fmax(p.a, std::fmax(p.b, p.c));
  const float lo = std::fmin(p.a, std::fmin(p.b, p.c));
  const float mid = -0.5f * (hi + lo);
  const float k = 1.0f / vbus;
  return {clamp(0.5f + (p.a + mid) * k, 0.0f, 1.0f), clamp(0.5f + (p.b + mid) * k, 0.0f, 1.0f),
          clamp(0.5f + (p.c + mid) * k, 0.0f, 1.0f)};
}

}  // namespace foc
