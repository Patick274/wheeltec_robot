#ifndef WHEELTEC_LIFT_MOTION_GATE_H
#define WHEELTEC_LIFT_MOTION_GATE_H

#include <array>
#include <cmath>
#include <cstdint>

// ROS-free policy. All times must come from the same monotonic clock.
// No permission, expired permission/command, or stale chassis feedback => zero output.
class LiftMotionGate {
 public:
  typedef std::array<double, 3> Velocity;
  explicit LiftMotionGate(std::uint64_t seed = 1) : next_id_(seed ? seed : 1) {}

  void command(const Velocity& value, double now) {
    command_ = valid(value) ? value : Velocity{{0, 0, 0}};
    command_time_ = now;
    if (!valid(value) || nonzero(value)) stationary_since_ = -1;
    update_request(now);
  }

  void feedback(const Velocity& value, double now) {
    const bool stopped = valid(value) && !nonzero(value);
    if (!fresh(feedback_time_, now, 0.5) || !stopped) stationary_since_ = -1;
    feedback_time_ = now;
    feedback_valid_ = valid(value);
    feedback_moving_ = feedback_valid_ && nonzero(value);
    if (stopped && stationary_since_ < 0) stationary_since_ = now;
  }

  void permit(std::uint64_t id, double now) {
    permit_id_ = (id == request_id_) ? id : 0;
    permit_time_ = now;
  }

  void tick(double now) { update_request(now); }
  std::uint64_t request_id() const { return request_id_; }
  bool permitted(double now) const {
    return request_id_ && permit_id_ == request_id_ && fresh(permit_time_, now, 0.3)
        && fresh(command_time_, now, 0.3) && feedback_valid_ && fresh(feedback_time_, now, 0.5);
  }
  Velocity output(double now) const {
    return permitted(now) ? command_ : Velocity{{0, 0, 0}};
  }

 private:
  static bool valid(const Velocity& v) {
    for (double n : v) if (!std::isfinite(n) || std::abs(n) > 32.767) return false;
    return true;  // Serial protocol is signed int16 after multiplication by 1000.
  }
  static bool nonzero(const Velocity& v) { return v[0] != 0 || v[1] != 0 || v[2] != 0; }
  static bool fresh(double stamp, double now, double timeout) {
    return stamp >= 0 && now >= stamp && now - stamp <= timeout;
  }
  void update_request(double now) {
    const bool demand = fresh(command_time_, now, 0.3) && nonzero(command_);
    const bool parked = feedback_valid_ && fresh(feedback_time_, now, 0.5)
        && stationary_since_ >= 0 && now - stationary_since_ >= 1.0;
    const bool measured_motion = feedback_moving_ && fresh(feedback_time_, now, 0.5);
    if (demand || measured_motion || (request_id_ && !parked)) {
      if (!request_id_) {
        request_id_ = next_id_++;
        if (!next_id_) ++next_id_;
        permit_id_ = 0;  // A new movement cannot reuse the previous permit.
      }
    } else {
      request_id_ = permit_id_ = 0;
    }
  }
  Velocity command_{{0, 0, 0}};
  double command_time_ = -1, feedback_time_ = -1, permit_time_ = -1;
  double stationary_since_ = -1;
  bool feedback_valid_ = false, feedback_moving_ = false;
  std::uint64_t next_id_, request_id_ = 0, permit_id_ = 0;
};
#endif
