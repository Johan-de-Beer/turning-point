"""Refit the expected-threat grid on the synthetic training matches and rewrite backend/xt_grid.json."""
from backend.xt import GRID_PATH, write


def main():
    grid = write()
    print(f"Wrote {GRID_PATH} from {grid['training']['matches']} synthetic matches ({grid['training']['actions']} actions).")


if __name__ == "__main__":
    main()
