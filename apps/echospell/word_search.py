"""
The grid for a Word search activity: every word hidden in a square of
letters, like the puzzles in the EchoSpell books.

Staff only give the words (one per question); the grid is built from them.
It's built from a seed, so it stays the same for every learner and every
reload, and changes only when the words do. Words run left to right, top to
bottom, or diagonally down to the right, never backwards, and may cross
where they share a letter.

    build(["cruel", "army"], seed="activity-7")
        {"size": 8, "rows": [["C", "R", ...], ...], "placed": 2}
"""

import math
import random
import string

DIRECTIONS = ((0, 1), (1, 0), (1, 1))     # across, down, diagonal
SMALLEST = 8
TRIES_AT_EACH_SIZE = 60


def letters_of(word):
    """What a word looks like in the grid: "ice cream" is ICECREAM."""
    return "".join(ch for ch in str(word or "").upper() if ch.isalpha())


def _place(grid, word, rng):
    """Put one word somewhere it fits; False if nowhere does."""
    size = len(grid)
    spots = [(r, c, d) for r in range(size) for c in range(size) for d in DIRECTIONS]
    rng.shuffle(spots)
    for r, c, (dr, dc) in spots:
        end_r, end_c = r + dr * (len(word) - 1), c + dc * (len(word) - 1)
        if end_r >= size or end_c >= size:
            continue
        cells = [(r + dr * i, c + dc * i) for i in range(len(word))]
        if all(grid[y][x] in ("", letter) for (y, x), letter in zip(cells, word)):
            for (y, x), letter in zip(cells, word):
                grid[y][x] = letter
            return True
    return False


def build(words, seed=""):
    words = sorted({letters_of(word) for word in words} - {""}, key=lambda w: (-len(w), w))
    rng = random.Random(f"{seed}:{','.join(words)}")
    longest = len(words[0]) if words else 0
    size = max(SMALLEST, longest, math.ceil(math.sqrt(sum(map(len, words)) * 2)))
    while True:
        for _ in range(TRIES_AT_EACH_SIZE):
            grid = [[""] * size for _ in range(size)]
            if all(_place(grid, word, rng) for word in words):
                filler = string.ascii_uppercase
                return {"size": size, "placed": len(words),
                        "rows": [[cell or rng.choice(filler) for cell in row] for row in grid]}
        size += 1                                   # too tight: a bigger square always fits
