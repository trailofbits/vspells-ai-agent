# The VAST Parser detection AI agent

This is an AI agent designed to communicate with the VAST parser dialect converter.

The VAST parser dialect converter can make use of externally-sourced information in order to make its conversions more accurate -- in a pre-AI world, this information would have come from a human operator receiving prompts in a VSCode session. This agent replaces the VSCode session and its human operator with Claude 3.7 Sonnet.

## Running

This project uses `uv` to run and manage its dependencies.

First, set the `ANTHROPIC_API_KEY` environment variable to a valid Claude API key.

Next, run `vast-detect-parsers` to listen on a Unix socket:

    vast-detect-parsers -vast-hl-to-parser=socket=/tmp/vast.sock -o parser.mlir input.mlir

Then, run the agent:

    uv run vspells-ai-agent /tmp/vast.sock

The AI ~~overlord~~ static analysis expert is now doing its thing.

## License

The VAST Parser detection AI agent is licensed according to the [Apache 2.0](LICENSE) license.

This research was developed with funding from the Defense Advanced Research Projects Agency (DARPA). The views, opinions and/or findings expressed are those of the author and should not be interpreted as representing the official views or policies of the Department of Defense or the U.S. Government.

Distribution Statement A – Approved for Public Release, Distribution Unlimited