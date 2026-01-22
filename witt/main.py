import sys
import interface.cli as cli

if __name__ == "__main__":
    try:
        cli.menu()
    except KeyboardInterrupt:
        sys.exit(0)

