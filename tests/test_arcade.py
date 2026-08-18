from vision.arcade import VisionArcade


def test_gesture_pong_responds_to_pointing():
    game = VisionArcade()
    game.start("gesture_pong")
    game.on_gesture("pointing", 0.2)
    assert game.state.score == 1
    assert game.state.hand_x == 0.2


def test_rps_maps_gestures_and_tracks_round():
    game = VisionArcade(rng=__import__("random").Random(1))
    game.start("rps")
    game.on_gesture("open hand")
    assert game.state.player_choice == "paper"
    assert game.state.cpu_choice in {"rock", "paper", "scissors"}


def test_unknown_game_is_rejected():
    try:
        VisionArcade().start("unknown")
    except ValueError:
        return
    assert False, "unknown arcade game should raise ValueError"


def test_shape_creator_and_floor_lava_use_cv_signals():
    game = VisionArcade()
    game.start("shape_creator")
    game.on_gesture("open hand")
    assert game.state.shape == "square"
    game.start("floor_lava")
    game.on_pose(True)
    assert game.state.score == 1
