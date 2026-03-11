#!/bin/bash
echo "Starting Chrome with Web Security (CSP) disabled..."
open -n -a "Google Chrome" --args --disable-web-security --user-data-dir="/tmp/chrome_dev_test"
echo "Chrome is now running in insecure mode for testing."
echo "You can now open the Aquera page and click the AI Help bookmarklet."
