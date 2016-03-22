""" Two1 command to update to the latest version of two1 and it's dependencies """
# standard python imports
import sys
import re
import os
import logging
import subprocess
from datetime import datetime
from datetime import date
from urllib.parse import urljoin
from distutils.version import LooseVersion

# 3rd party requests
import requests
import click

# two1 imports
import two1
from two1.commands.util import uxstring
from two1.commands.util import decorators
from two1.commands.util import exceptions


TWO1_APT_INSTALL_PACKAGE_PATH = "/usr/lib/python3/dist-packages/" + two1.TWO1_PACKAGE_NAME


# Creates a ClickLogger
logger = logging.getLogger(__name__)


@click.command()
@click.argument('version', nargs=1, required=False, default='latest')
@click.pass_context
@decorators.catch_all
@decorators.capture_usage
def update(ctx, version):
    """Update the 21 Command Line Interface.

\b
Usage
-----
Invoke this with no arguments to update the CLI.
$ 21 update
"""
    _update(ctx.obj['config'], version)


def _update(config, version):
    logger.info(uxstring.UxString.update_check)
    update_two1_package(config, version, force_update_check=True)


def update_two1_package(config, version, force_update_check=False):
    """ Handles the updating of the CLI software including any dependencies.

        How does the update work?
        The entry point function to run the updater is update(self).
        Update steps
        1) If update check has not been performed today, check to see if an
           update is available.
        2) If a new version is available, run the updater and reset the update
           check.

        Key State Variables in the config:
            config.last_update_check (string): This stores the last date on
            which an update check was performed in %Y-%m-%d format.

        Args:
            config (Config): Config context object
            version (string): The requested version of 21 to install (defaults
                to 'latest')
            force_update_check (bool): Forces an update check with the pypi
            service

        Returns:
            dict: A dict with two keys are returned.
                  update_available (bool): Whether an update is available.
                  update_successful (bool): Whether the update was successfully
                  downloaded and installed.
    """
    ret = dict(
        update_available=False,
        update_successful=None
    )
    # Has update been already performed today?
    if not force_update_check and checked_for_an_update_today(config):
        # do nothing
        pass
    else:
        # Set the update check date to today. There are several schools of
        # thought on this. This could be done after a successful update as
        # well.
        config.set('last_update_check', date.today().strftime("%Y-%m-%d"), should_save=True)

        installed_version = two1.TWO1_VERSION

        if installed_version == '':
            # This has occured when local git commits have happened
            raise exceptions.Two1Error(uxstring.UxString.Error.version_not_detected)

        try:
            latest_version = lookup_pypi_version(version)
        except exceptions.Two1Error:
            raise
        except Exception:
            _do_update('latest')

        # Check if available version is more recent than the installed version.
        if (LooseVersion(latest_version) > LooseVersion(installed_version) or
                version != 'latest'):
            ret["update_available"] = True
            # An updated version of the package is available.
            # The update is performed either using pip or apt-get depending
            # on how two1 was installed in the first place.
            logger.info(uxstring.UxString.update_package.format(latest_version))

            # Detect if the package was installed using apt-get
            # This detection only works for deb based linux systems
            _do_update(latest_version)
        else:
            # Alert the user if there is no newer version available
            logger.info(uxstring.UxString.update_not_needed)

        ret["update_successful"] = True

    return ret


def _do_update(version):
    """ Actually does the update
    """
    if os.path.isdir(TWO1_APT_INSTALL_PACKAGE_PATH):
        perform_apt_based_update()
    else:
        perform_pip_based_update(version)


def stop_walletd():
    """Stops the walletd process if it is running.
    """
    from two1.wallet import daemonizer
    from two1.wallet.exceptions import DaemonizerError
    failed = False
    try:
        d = daemonizer.get_daemonizer()
        if d.started():
            if not d.stop():
                failed = True
    except OSError:
        pass
    except DaemonizerError:
        failed = True

    return not failed


def lookup_pypi_version(version='latest'):
    """Get the latest version of the software from the PyPi service.

    Args:
        version (string): The requested version number, sha hash, or relative
        timing of the released package to install.
        Example: '0.2.1', '8e15eb1', 'latest'

    Returns:
        version (string): A version string with period delimited major,
        minor, and patch numbers.
        Example: '0.2.1'
    """
    try:
        url = urljoin(two1.TWO1_PYPI_HOST, "api/package/{}/".format(two1.TWO1_PACKAGE_NAME))
        r = requests.get(url)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        raise exceptions.Two1Error(uxstring.UxString.Error.update_server_connection)

    try:
        data = r.json()
    except ValueError:
        raise exceptions.Two1Error(uxstring.UxString.Error.version_not_found.format(version))

    pypi_version = None

    try:
        packages = data["packages"]

        if version != "latest":
            # Find the requested version or commit
            data = next((p for p in packages if version == p["version"]), None)
            # Prefer stable versions over unstable (e.g. exact matches first)
            if not data:
                data = next((p for p in packages if version in p["version"]), None)
        else:
            # Find the latest stable version matching '1.2' or '1.2.3'
            data = next((p for p in packages if re.search(r'\d\.\d(\.\d)?$', p["version"])), None)

        if not data:
            raise exceptions.Two1Error(uxstring.UxString.Error.version_not_found.format(version))
        else:
            pypi_version = data["version"]

    except (AttributeError, KeyError, TypeError):
        raise exceptions.Two1Error(uxstring.UxString.Error.version_not_found.format(version))

    return pypi_version


def checked_for_an_update_today(config):
    """ Checks if an update check was performed today

    Args:
        config (Config): Config context

    Returns:
        bool: True if an update check has already been performed today,
              False otherwise
    """
    try:
        last_update_check = config.last_update_check
        last_update_check_date = datetime.strptime(last_update_check, "%Y-%m-%d").date()
        today_date = date.today()
        # Check if last_update_check was performed before today
        if today_date > last_update_check_date:
            ret = False
        else:
            ret = True

    except AttributeError:
        # missing attribute could be due to several reasons
        # but we must check for an update in this case
        ret = False

    return ret


def perform_pip_based_update(version):
    """ This will use pip3 to update the package (without dependency update)
    """

    install_command = ["pip3",
                       "install",
                       "-i",
                       "{}/pypi".format(two1.TWO1_PYPI_HOST),
                       "-U",
                       "--no-deps",
                       "-I",
                       "{}=={}".format(two1.TWO1_PACKAGE_NAME, version)]

    stop_walletd()

    try:
        # Inside a virtualenv, sys.prefix points to the virtualenv directory,
        # and sys.real_prefix points to the "real" prefix of the system Python
        # (often /usr or /usr/local or some such).
        if hasattr(sys, "real_prefix"):
            subprocess.check_call(install_command)
        else:
            logger.info(uxstring.UxString.update_superuser)
            # If not in a virtual environment, run the install command
            # with sudo permissions.
            subprocess.check_call(["sudo"] + install_command)
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        raise exceptions.Two1Error(uxstring.UxString.Error.update_failed)


def perform_apt_based_update():
    """ This will perform an apt-get based update.
    """

    stop_walletd()

    update_command = ["sudo",
                      "apt-get",
                      "update"]
    upgrade_command = ["sudo",
                       "apt-get",
                       "-y",
                       "install",
                       "--only-upgrade",
                       two1.TWO1_PACKAGE_NAME,
                       "minerd",
                       "zerotier-one"]
    try:
        subprocess.check_call(update_command)
        subprocess.check_call(upgrade_command)
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        raise exceptions.Two1Error(uxstring.UxString.Error.update_failed)
