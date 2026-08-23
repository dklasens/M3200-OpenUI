#!/bin/sh
# Optional release hook, run as root on the device AFTER the agent, dashboard
# and service unit have been applied, before the agent restarts.
#
# Ship device-side changes with a release by editing this file, e.g. the
# guarded EFS toggle used to enable 5G SA on Vodafone:
#
#   EFS=/nv/item_files/modem/mmode/nr5g_disable_mode
#   [ "$(cat $EFS 2>/dev/null)" = "01" ] && printf '00' > $EFS
#
# A non-zero exit aborts the install result (files are already in place but
# the agent still restarts), and the failure is shown in the dashboard.
exit 0
