"""Deterministic game state for Kaizumi Vision Arcade."""

from __future__ import annotations

import random
import time
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
    shape: str = "circle"
    note: str = "C"
    planet_x: float = 0.5
    pose_active: bool = False
    rounds: int = 0
    streak: int = 0
    target_x: float = 0.5
    level: int = 1
    combo: int = 0


class VisionArcade:
    """Game rules independent from Tk/camera code for easy testing."""

    def __init__(self, rng=None):
        self.state = ArcadeState()
        self._rng = rng or random.Random()

    def start(self, game: str) -> ArcadeState:
        game = game.lower().strip()
        if game not in {"face_filter", "gesture_pong", "rps", "shape_creator", "orb_hunt",
                        "floor_lava", "planet_explorer", "whirlpool", "laser_defense",
                        "arpeggiator"}:
            raise ValueError(f"Unknown arcade game: {game}")
        self.state = ArcadeState(game=game, message="Show your gesture")
        self._last_gesture = ""
        self._last_action_at = 0.0
        self._last_pose = False
        if game == "face_filter":
            self.state.message = "Move your head — filter locked"
        elif game == "gesture_pong":
            self.state.message = "Point left/right to move"
        else:
            self.state.message = "Show rock, paper or scissors"
        if game == "shape_creator":
            self.state.message = "Point to move · open hand changes shape"
        elif game == "floor_lava":
            self.state.message = "Raise both arms to jump"
        elif game == "planet_explorer":
            self.state.message = "Point to explore the planet"
        elif game == "whirlpool":
            self.state.message = "Wave your hand to bend the camera"
        elif game == "laser_defense":
            self.state.message = "Point to fire · open hand shields"
        elif game == "arpeggiator":
            self.state.message = "Move your hand across the notes"
        elif game == "orb_hunt":
            self.state.message = "Point at the orb · hit 5 to level up"
        return self.state

    def stop(self) -> ArcadeState:
        self.state = ArcadeState(message="Arcade paused")
        return self.state

    def on_gesture(self, gesture: str, x: float = 0.5) -> ArcadeState:
        gesture = gesture.lower().strip()
        self.state.hand_x = max(0.0, min(1.0, float(x)))
        now = time.monotonic()
        action_games = {"gesture_pong", "rps", "shape_creator", "orb_hunt", "laser_defense"}
        if (self.state.game in action_games and gesture == self._last_gesture
                and now - self._last_action_at < 0.55):
            return self.state
        self._last_gesture = gesture
        self._last_action_at = now
        if self.state.game == "gesture_pong":
            if gesture in {"pointing", "one finger (index)"}:
                if abs(self.state.hand_x - self.state.target_x) <= 0.35:
                    self.state.score += 1
                    self.state.target_x = self._rng.random()
                    self.state.message = "PADDLE HIT · NEW TARGET"
                else:
                    self.state.lives = max(0, self.state.lives - 1)
                    self.state.message = "MISS · FOLLOW THE TARGET"
            elif gesture == "fist":
                self.state.lives = max(0, self.state.lives - 1)
                self.state.message = "MISS"
        elif self.state.game == "orb_hunt":
            if gesture in {"pointing", "one finger (index)"}:
                window = max(0.08, 0.24 - self.state.level * 0.015)
                if abs(self.state.hand_x - self.state.target_x) <= window:
                    self.state.score += 1
                    self.state.combo += 1
                    self.state.level = 1 + self.state.score // 5
                    self.state.target_x = self._rng.random()
                    self.state.message = f"ORB HIT · COMBO x{self.state.combo}"
                else:
                    self.state.lives = max(0, self.state.lives - 1)
                    self.state.combo = 0
                    self.state.message = "MISS · TRACK THE ORB"
        elif self.state.game == "shape_creator":
            if gesture == "open hand":
                self.state.shape = {"circle": "square", "square": "triangle", "triangle": "circle"}[self.state.shape]
                self.state.message = f"SHAPE: {self.state.shape.upper()}"
        elif self.state.game == "planet_explorer":
            self.state.planet_x = self.state.hand_x
            self.state.message = f"EXPLORING {int(self.state.hand_x * 360)}°"
        elif self.state.game == "whirlpool":
            self.state.score += 1 if gesture in {"open hand", "pointing"} else 0
            self.state.message = "WAVE FIELD ACTIVE"
        elif self.state.game == "laser_defense":
            if gesture == "pointing":
                self.state.score += 1
                self.state.message = "LASER FIRED"
            elif gesture == "open hand":
                self.state.message = "SHIELD UP"
        elif self.state.game == "arpeggiator":
            notes = ["C", "D", "E", "G", "A"]
            self.state.note = notes[min(len(notes) - 1, int(self.state.hand_x * len(notes)))]
            self.state.score += 1
            self.state.message = f"NOTE {self.state.note}"
        elif self.state.game == "rps" and gesture in RPS_MAP:
            self.state.player_choice = RPS_MAP[gesture]
            self.state.cpu_choice = self._rng.choice(["rock", "paper", "scissors"])
            self.state.rounds += 1
            if self.state.player_choice == self.state.cpu_choice:
                self.state.streak = 0
                self.state.message = "DRAW"
            elif (self.state.player_choice, self.state.cpu_choice) in {
                ("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")
            }:
                self.state.score += 1
                self.state.streak += 1
                self.state.message = "YOU WIN"
            else:
                self.state.lives = max(0, self.state.lives - 1)
                self.state.streak = 0
                self.state.message = "KAIZUMI WINS"
        return self.state

    def on_pose(self, arms_raised: bool, lean: float = 0.0) -> ArcadeState:
        self.state.pose_active = bool(arms_raised)
        if self.state.game == "floor_lava":
            if arms_raised and not self._last_pose:
                self.state.score += 1
                self.state.message = "JUMP — SAFE!"
            elif not arms_raised:
                self.state.message = "LAVA RISING — RAISE ARMS"
        self._last_pose = bool(arms_raised)
        return self.state
