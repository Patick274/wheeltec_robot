#include "lift_motion_gate.h"
#include <cassert>
#include <iostream>
#include <limits>
#include <string>

typedef LiftMotionGate::Velocity V;
int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string test(argv[1]);
  LiftMotionGate gate(1000);
  gate.feedback(V{{0, 0, 0}}, 0);
  gate.command(V{{0.2, 0, 0}}, 0);
  const std::uint64_t first = gate.request_id();
  assert(first != 0);
  if (test == "wait_for_permit") {
    assert(gate.output(0)[0] == 0);
    gate.permit(first, 0.1);
    assert(gate.output(0.1)[0] == 0.2);
  } else if (test == "permit_timeout") {
    gate.permit(first, 0);
    gate.command(V{{0.2, 0, 0}}, 0.31);
    gate.feedback(V{{0.2, 0, 0}}, 0.31);
    gate.tick(0.31);
    assert(gate.output(0.31)[0] == 0);
    assert(gate.request_id() == first);
  } else if (test == "command_timeout") {
    gate.permit(first, 0.31);
    gate.feedback(V{{0, 0, 0}}, 0.31);
    gate.tick(0.31);
    assert(gate.output(0.31)[0] == 0);
  } else if (test == "feedback_timeout") {
    gate.command(V{{0.2, 0, 0}}, 0.6);
    gate.permit(first, 0.6);
    gate.tick(0.6);
    assert(gate.output(0.6)[0] == 0);
    assert(gate.request_id() == first);
  } else if (test == "zero_and_cooldown") {
    gate.permit(first, 0.1);
    gate.command(V{{0, 0, 0}}, 0.1);
    gate.feedback(V{{0.005, 0, 0}}, 0.1);
    gate.tick(0.1);
    assert(gate.output(0.1)[0] == 0 && gate.request_id() == first);
    for (int i = 2; i <= 13; ++i) {
      gate.feedback(V{{0, 0, 0}}, i * 0.1);
      gate.tick(i * 0.1);
      if (i < 12) assert(gate.request_id() == first);
    }
    assert(gate.request_id() == 0);
    gate.command(V{{0.2, 0, 0}}, 1.31);
    assert(gate.request_id() != first);
    gate.permit(first, 1.31);
    assert(gate.output(1.31)[0] == 0);
  } else if (test == "tiny_command") {
    gate.command(V{{0.005, 0, 0}}, 0.1);
    assert(gate.output(0.1)[0] == 0);
    gate.permit(first, 0.1);
    assert(gate.output(0.1)[0] == 0.005);
  } else if (test == "invalid_command") {
    gate.permit(first, 0.1);
    gate.command(V{{std::numeric_limits<double>::quiet_NaN(), 0, 0}}, 0.1);
    assert(gate.output(0.1)[0] == 0);
    gate.command(V{{33, 0, 0}}, 0.2);
    assert(gate.output(0.2)[0] == 0);
  } else if (test == "old_process") {
    LiftMotionGate restarted(2000);
    restarted.feedback(V{{0, 0, 0}}, 0.1);
    restarted.command(V{{0.2, 0, 0}}, 0.1);
    restarted.permit(first, 0.1);
    assert(restarted.output(0.1)[0] == 0);
  } else if (test == "uncommanded_motion") {
    LiftMotionGate idle(3000);
    idle.feedback(V{{0.005, 0, 0}}, 0.1);
    idle.tick(0.1);
    assert(idle.request_id() == 3000);
    assert(idle.output(0.1)[0] == 0);
  } else {
    return 2;
  }
  std::cout << test << " OK\n";
}
