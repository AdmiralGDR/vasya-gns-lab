# SPDX-License-Identifier: GPL-3.0-or-later
# Example environment for the optional integration tests. Copy, adjust the paths, then `source` it.
# Every variable is optional; a test whose input is missing is skipped with the reason.
export VASYA_GNS3SERVER_BIN="$HOME/.venvs/gns3/bin/gns3server"   # gns3server 2.2.61 for runtime tests
# export VASYA_TEST_PATH="$HOME/vasya-tools/bin"                   # extra PATH (dynamips, ubridge, vpcs)
# export VASYA_TEST_GNS3RT=build/gns3rt                            # bundled gns3server build tree
# export VASYA_TEST_STAGE=build/stage/VASYA-GNS-LAB-1.1.0          # staged bundle (build_bundle.py)
# export VASYA_TEST_PACK=/path/to/Pack                             # private image pack
# export VASYA_TEST_NETWORK=1                                      # tests that download from the internet
export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src"
