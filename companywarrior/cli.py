from email.policy import default
import click
import subprocess
import socket
import logging
import json
import re
from rich import print
from rich.logging import RichHandler
from rich.console import Console
import os
import datetime

# # The issue with android
# https://forum.xda-developers.com/t/how-do-i-assign-a-permanent-static-ip-address-to-hotspot-in-android-10.4037021/

APP_NAME = "company-warrior"
DEFAULT_CFG = os.path.join(click.get_app_dir(APP_NAME), "config.json")

FORMAT = "%(message)s"
logging.basicConfig(
    level=logging.DEBUG, format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


def nmcli_connect(name: str):
    connection_result = subprocess.run(
        ["nmcli", "con", "up", name], capture_output=True, encoding="UTF-8"
    )
    if connection_result.returncode != 0:
        logging.error(connection_result)
        logging.error(
            "unable to connect to hotspot.\n Enable the hotspot and try again.\n"
        )
        exit(connection_result.returncode)
    else:
        logging.info(connection_result)


def get_active_wg_interfaces():
    """returns a list of active wireguard interfaces"""
    wg_show_compl_proc = subprocess.run(
        ["sudo", "wg", "show"], capture_output=True, encoding="UTF-8"
    )
    interfaces = filter(
        lambda line: "interface" in line, wg_show_compl_proc.stdout.split("\n")
    )
    wg_interfaces = []
    for interface in interfaces:
        wg_interfaces.append(interface.replace("interface: ", ""))
    return wg_interfaces


def _wg_connect(cfg_name: str, state: str):
    wg_up_result = subprocess.run(
        ["sudo", "wg-quick", state, cfg_name], capture_output=True, encoding="UTF-8"
    )
    if wg_up_result.returncode != 0:
        logging.error(wg_up_result)
        logging.error(
            "make shure you are allowed to run wg-quick with sudo and without password"
        )
        exit(wg_up_result.returncode)
    else:
        logging.info(wg_up_result)


def get_wifi_ip(nmcli_profile: str):
    nmcli_proc_result = subprocess.run(
        ["nmcli", "con", "show", nmcli_profile], capture_output=True
    )
    return re.search(
        r"IP4.ADDRESS\[[0-9]+\]:\s+([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})",
        str(nmcli_proc_result.stdout),
    ).group(1)


def add_printer(printer, last_octet, nmcli_connection_name: str):
    (
        printer_queue,
        printer_driver,
        printer_media,
        printer_connection_string,
    ) = printer
    machine_ip_address_octets = socket.gethostbyname(socket.gethostname()).split(
        sep="."
    )  # Get the Wifi IP
    machine_ip_address_octets = get_wifi_ip(nmcli_connection_name).split(sep=".")
    printer_ip = f"{machine_ip_address_octets[0]}.{machine_ip_address_octets[1]}.{machine_ip_address_octets[2]}.{last_octet}"
    logging.info(f"printer ip address = {printer_ip}")
    if last_octet:
        printer_connection_string = printer_connection_string.replace(
            "xxx.xxx.xxx.xxx", printer_ip
        )  # f"hp:/net/OfficeJet_250_Mobile_Series?ip={printer_ip}"
    printer_remove_result = subprocess.run(["lpadmin", "-x", printer_queue])
    if printer_remove_result.returncode != 0:
        logging.error(printer_remove_result)
    else:
        logging.info(printer_remove_result)

    # 4. add the printer with current subnet 192.168.xxx.93
    printer_add_result = subprocess.run(
        [
            "lpadmin",
            "-p",
            printer_queue,
            "-E",
            "-v",
            printer_connection_string,
            "-m",
            printer_driver,
            "-o",
            f"media={printer_media}",
        ]
    )
    if printer_add_result.returncode != 0:
        logging.error(printer_add_result)
        exit(printer_add_result.returncode)
    else:
        logging.info(printer_add_result)
    printer_options_result = subprocess.run(["lpoptions", "-d", printer_queue])
    if printer_options_result.returncode != 0:
        logging.error(printer_options_result)
    else:
        logging.info(printer_options_result)


def wg_connect(cfg_name: str):
    _wg_connect(cfg_name=cfg_name, state="up")


def wg_disconnect(cfg_name: str):
    _wg_connect(cfg_name=cfg_name, state="down")


def configure_roadwarrior(ctx, param, filename):
    """reads the config file sets the defaults to the values in the config file"""
    logging.debug(f"ctx {ctx}")
    logging.debug(f"param {param}")
    logging.debug(f"filename {filename}")
    with open(filename, "r") as cfg_file:
        cfg = json.load(cfg_file)
        print(cfg)
        roadwarrior_options = cfg["roadwarrior"]
        ctx.default_map = roadwarrior_options


@click.command()
@click.option(
    "-c",
    "--config",
    default=DEFAULT_CFG,
    callback=configure_roadwarrior,
    is_eager=True,
    type=click.Path(dir_okay=False),
    expose_value=False,
)
@click.option(
    "-n",
    "--nmcli-connection-name",
    metavar="<name>",
    show_default=True,
    help='connection name, to list available connections use "nmcli con show"',
)
@click.option(
    "-p",
    "--printer",
    type=(str, str, str, str),
    metavar="<printer_queue> <printer_driver> <printer_paper> <printer_connection_string>",
    show_default=True,
)
@click.option(
    "-w",
    "--wireguard-config",
    metavar="<wireguard config file>",
    help='wireguard config file. If your config is stored under /etc/wireguard/wg0.conf you have to pass "wg0"',
    show_default=True,
)
@click.option(
    "-l",
    "--launch",
    help="Launch an App or URI",
    multiple=True,
)
@click.option(
    "-a",
    "--android-hotspot-mode",
    "printer_ip_last_octet_android_hotspot",
    help="Enable this if you are using Android 11 and up to determine the ip address of the printer. In the connection string enter xxx.xxx.xxx.xxx instead of the ip address. This script replaces the ip with the correct ip address",
    metavar="<mobile-printer-last-octet>",
)
def roadwarrior(
    nmcli_connection_name,
    printer,
    wireguard_config,
    launch,
    printer_ip_last_octet_android_hotspot,
):
    """A simple command to setup your mobile office with Android phones. Android changes the subnet every reboot of the phone,
    this script gets the wifi IP address and sets everything up for remote work. It updates the IP address of your mobile printer to the same subnet
    and establishes a wireguard vpn connection.

    \bThis script requires:

    \b    cups (Common Unix Printing Service)

    \b    wireguard (wg-quick command)

    \b      sudo hast to be configured to run wg-quick without password

    \b    nmcli

    Tested on Arch Linux with Gnome Shell"""

    console = Console()

    # 1. connect to Mobile Phone
    # nmcli con up {nmcli_connection_name}
    if nmcli_connection_name:
        nmcli_connect(nmcli_connection_name)

    # 3. setup the printer
    if printer:
        add_printer(
            printer, printer_ip_last_octet_android_hotspot, nmcli_connection_name
        )

    # 5. establish wireguard connection
    for connection_interface in get_active_wg_interfaces():
        wg_disconnect(connection_interface)
    if wireguard_config:
        wg_connect(wireguard_config)

    # Launch Apps
    if launch:
        for app in launch:
            click.launch(app)


@click.command()
def officewarrior():
    print("Welcome to the Office")


@click.command()
@click.argument("profile")
@click.option(
    "-c",
    "--config",
    default=DEFAULT_CFG,
    type=click.Path(dir_okay=False),
    show_default=True,
    metavar="<config file path>",
    help="read default options from config.ini file",
)
# TODO implement these options
# @click.option("--add-profile", is_flag=True)
# @click.option("-r", "--remove-profile", "r_profile")
def companywarrior(config, profile):
    with open(config, "r") as cfg_file:
        cfg = json.load(cfg_file)
    logging.debug(cfg)
    if "nmcli_connection_name" in cfg[profile].keys():
        nmcli_connect(cfg[profile]["nmcli_connection_name"])
    if "printer" in cfg[profile].keys():
        if "printer_ip_last_octet_android_hotspot" in cfg[profile].keys():
            printer_ip_last_octet_android_hotspot = cfg[profile][
                "printer_ip_last_octet_android_hotspot"
            ]
        else:
            printer_ip_last_octet_android_hotspot = None
        add_printer(
            cfg[profile]["printer"],
            printer_ip_last_octet_android_hotspot,
            cfg[profile]["nmcli_connection_name"],
        )
    for active_wg_conenction in get_active_wg_interfaces():
        wg_disconnect(active_wg_conenction)
    if "wireguard_config" in cfg[profile].keys():
        wg_connect(cfg[profile]["wireguard_config"])
    if "launch" in cfg[profile].keys():
        for app in cfg[profile]["launch"]:
            click.launch(app)


if __name__ == "__main__":
    roadwarrior()
