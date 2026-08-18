"""Deterministic game state for Kaizumi Vision Arcade."""

from __future__ import annotations

import random
from dataclasses import dataclass


GESTURES = {"fist", "open hand", "peace sign", "pointing", "one finger (index)"}
RPS_MAP = {"fist": "rock", "open hand": "paper", "peace sign": "scissors"}


@dataclass(slots=True)
class ArcadeState:
    game: str = "idle"
    score: int = 0
    lives: int = 3
    message: str = "Choose a game"
    hand_x: float = 0.5
    player_choice: str = ""
    cpu_choice: str = ""
    face_filter: str = "CYBER VISOR"


class VisionArcade:
    """Game rules independent from Tk/camera code for easy testing."""

    def __init__(self, rng=None):
        self.state = ArcadeState()
        self._rng = rng or random.Random()

    def start(self, game: str) -> ArcadeState:
        game = game.lower().strip()
        if game not in {"face_filter", "gesture_pong", "rps"}:
            raise ValueError(f"Unknown arcade game: {game}")
        self.state = ArcadeState(game=game, message="Show your gesture")
        if game == "face_filter":
            self.state.message = "Move your head — filter locked"
        elif game == "gesture_pong":
            self.state.message = "Point left/right to move"
        else:
            self.state.message = "Show rock, paper or scissors"
        return self.state

    def stop(self) -> ArcadeState:
        self.state = ArcadeState(message="Arcade paused")
        return self.state

    def on_gesture(self, gesture: str, x: float = 0.5) -> ArcadeState:
        gesture = gesture.lower().strip()
        self.state.hand_x = max(0.0, min(1.0, float(x)))
        if self.state.game == "gesture_pong":
            if gesture in {"pointing", "one finger (index)"}:
                self.state.score += 1
                self.state.message = "PADDLE HIT"
            elif gesture == "fist":
                self.state.lives = max(0, self.state.lives - 1)
                self.state.message = "MISS"
        elif self.state.game == "rps" and gesture in RPS_MAP:
            self.state.player_choice = RPS_MAP[gesture]
            self.state.cpu_choice = self._rng.choice(["rock", "paper", "scissors"])
            if self.state.player_choice == self.state.cpu_choice:
                self.state.message = "DRAW"
            elif (self.state.player_choice, self.state.cpu_choice) in {
                ("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")
            }:
                self.state.score += 1
                self.state.message = "YOU WIN"
            else:
                self.state.lives = max(0, self.state.lives - 1)
                self.state.message = "KAIZUMI WINS"
        return self.state
