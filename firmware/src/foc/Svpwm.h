#pragma once
// -----------------------------------------------------------------------------
// Space-vector modulation by min-max (midpoint) injection.
//
// The three phase voltages get a common-mode offset that centres the highest
// and lowest between the rails. The motor neutral floats, so the offset does
// not reach the windings, and the usable vector grows from V_bus/2 (plain
// sine) to V_bus/√3, the circle inscribed in the hexagon.
//
// Duties are high-side on-fractions, 0..1, centre-aligned. A vector larger
// than V_bus/√3 is scaled back onto that circle (the current loop limits
// earlier; this is the last guard), so the output never leaves the linear
// region and always reproduces the requested direction.
// -----------------------------------------------------------------------------
#include "foc/Math.h"

namespace foc {

struct Duty3 {
  float a, b, c;
};

// Largest vector magnitude the bridge can produce at this bus voltage.
inline float linearLimit(float vbus) { return vbus * kInvSqrt3; }

Duty3 svpwm(AlphaBeta v, float vbus);

}  // namespace foc
