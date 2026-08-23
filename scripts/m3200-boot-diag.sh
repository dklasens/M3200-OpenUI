#!/bin/sh
# Bounded early-boot diagnostics for controlled SIM and radio-mode tests.
#
# Six 180-second slots are retained under /data/m3200-openui/boot-diag.  The
# logger deliberately avoids subscriber identifiers (IMSI, ICCID, MSISDN).

set -u

base=/data/m3200-openui/boot-diag
slots=6
interval=2
max_seconds=180
index_file="$base/next-slot"

mkdir -p "$base" || exit 1

slot=0
if [ -r "$index_file" ]; then
    candidate=$(cat "$index_file" 2>/dev/null)
    case "$candidate" in
        0|1|2|3|4|5) slot=$candidate ;;
    esac
fi

next=$((slot + 1))
if [ "$next" -ge "$slots" ]; then
    next=0
fi
printf '%s\n' "$next" > "$index_file.tmp"
mv -f "$index_file.tmp" "$index_file"

log="$base/boot-$slot.log"
: > "$log"
chmod 600 "$log"

value()
{
    if [ -r "$1" ]; then
        tr -d '\n' < "$1" 2>/dev/null
    else
        printf '-'
    fi
}

target_state()
{
    state=$(systemctl is-active "$1" 2>/dev/null)
    case "$state" in
        active|inactive|activating|deactivating|failed) printf '%s' "$state" ;;
        *) printf unknown ;;
    esac
}

event_tail()
{
    if [ -r /var/log/messages ]; then
        printf '%s\n' '--- relevant vendor-log tail ---' >> "$log"
        tail -n 400 /var/log/messages 2>/dev/null |
            grep -E 'PMIC PON|Power-on reason|power_on_cause|power_button|usb_det|charger_det|battery_det|State change from|Timer [Ss]hut down|Received Timer Shutdown|DMS_OP_MODE|Sending Power Down|Rebooting the device|Current PLMN|uim_get_sim_state' |
            tail -n 120 >> "$log"
    fi
}

finish()
{
    printf 'end time=%s uptime=%s\n' "$(date -Iseconds 2>/dev/null || date)" "$(value /proc/uptime)" >> "$log"
    event_tail
    sync
    exit 0
}

trap finish HUP INT TERM

printf 'm3200 boot diagnostic slot=%s\n' "$slot" >> "$log"
printf 'start time=%s boot_id=%s uptime=%s\n' \
    "$(date -Iseconds 2>/dev/null || date)" \
    "$(value /proc/sys/kernel/random/boot_id)" \
    "$(value /proc/uptime)" >> "$log"
printf '%s\n' '--- reset and modem kernel lines ---' >> "$log"
dmesg 2>/dev/null |
    grep -E 'PMIC PON|Power-on reason|watchdog|subsys-restart|modem:|Modem is up' |
    tail -n 120 >> "$log"
event_tail
sync

elapsed=0
sequence=0
while [ "$elapsed" -lt "$max_seconds" ]; do
    printf 'sample=%s uptime=%s battery_present=%s battery_status=%s battery_capacity=%s usb_present=%s usb_online=%s online=%s low_power=%s shutdown=%s\n' \
        "$sequence" \
        "$(value /proc/uptime)" \
        "$(value /sys/class/power_supply/battery/present)" \
        "$(value /sys/class/power_supply/battery/status)" \
        "$(value /sys/class/power_supply/battery/capacity)" \
        "$(value /sys/class/power_supply/usb/present)" \
        "$(value /sys/class/power_supply/usb/online)" \
        "$(target_state online.target)" \
        "$(target_state low-power-mode.target)" \
        "$(target_state shutdown.target)" >> "$log"

    if [ $((sequence % 5)) -eq 0 ]; then
        logger -t m3200-boot-diag \
            "sample=$sequence uptime=$(value /proc/uptime) battery=$(value /sys/class/power_supply/battery/present) usb=$(value /sys/class/power_supply/usb/online) online=$(target_state online.target)" 2>/dev/null
        sync
    fi

    sleep "$interval"
    elapsed=$((elapsed + interval))
    sequence=$((sequence + 1))
done

finish
