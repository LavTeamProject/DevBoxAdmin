# Installing Service Admin on a clean Mac (with screenshots)

_The screenshots show the Russian interface; switch to English with the RU / EN buttons in the panel header._

This guide was verified **on a real clean macOS 26.6 in a virtual machine** (image `macos-tahoe-vanilla`: no Command Line Tools,
Homebrew, Git, or Python — exactly a "freshly installed system"). All screenshots were taken there. The installer in the VM ran in English (based on the guest's `LANG`);
on your Mac it will be in Russian unless the system language is English (to force a language: `SA_LANG=ru` / `SA_LANG=en`).

**What you get:** the "Service Admin" app in Applications, the panel server that starts at login, and the panel in your browser at
`http://127.0.0.1:8765` (reachable only from this Mac).

**Requirements:** a Mac with Apple Silicon, macOS 13 or newer, an internet connection, and about 100 MB of free space (the bundled Python takes ~70 MB). Administrator rights are **not needed** at this stage.
For the next steps (Command Line Tools and Homebrew): **≥ 25 GB free** if you install through the Apple dialog (otherwise use `softwareupdate`, see step 4.1); **turn off your VPN** during installation if it routes all traffic.

---

## Step 1. Put the project folder on the Mac

A clean Mac has no `git`, so the easiest way is to copy the `mac-service-admin` folder (as an archive, via AirDrop, or from a flash drive) into your home folder, for example to
`~/service-admin`. If you already have Command Line Tools and `git`, `git clone` works too.

> The folder must be **outside** `~/Documents`, `~/Desktop`, and `~/Downloads`: otherwise macOS will ask for permission to access those
> folders on first launch (no big deal — click "Allow" — but it is simpler to avoid it).

![Clean macOS desktop](../img/01-clean-desktop.jpg)

---

## Step 2. Open Terminal and run the installer

1. Press **⌘ Space**, type `Terminal`, press Enter.
2. Run:
   ```bash
   cd ~/service-admin
   ./install.sh
   ```
3. The installer does everything needed **by itself** (detailed output below), asks nothing, and installs nothing from Homebrew:
   * downloads its own **Python 3.12** (python-build-standalone) to `~/.service-admin/runtime/python`, **verifies the checksum**, and unpacks it.
     The system Python is not needed — a clean Mac does not have one anyway;
   * builds the launcher app with macOS tools (`osacompile`);
   * puts `Service Admin.app` into `/Applications` (or `~/Applications` if you have no write permission there);
   * sets up the server to start at login (LaunchAgent `local.service-admin`);
   * starts the server and checks that it responds.

![The installer at work: downloading and verifying Python](../img/02-install-running.jpg)

At the end you will see the "Готово / Done" line. The server is already running at `http://127.0.0.1:8765`.

![Installation finished](../img/03-install-finished.jpg)

**The macOS notification "App Background Activity — python3 can run in the background"** is normal: macOS is telling you that a background process
(the panel server) has appeared. You do not need to click anything. You can manage it in **System Settings → General → Login Items & Extensions**.

If the server "is not responding yet" and a dialog "Python would like to access files in…" appeared, click **"Allow"**: the server will carry on by itself.

---

## Step 3. Open the "Service Admin" app

The app is in Applications (Finder → Applications). You can open it from **Spotlight** (⌘ Space → `Service Admin`), **Launchpad**, or the **Dock**
(drag the icon to the Dock to keep it at hand).

![Service Admin in the Applications folder](../img/04-applications-folder.jpg)

The app is a small launcher: it checks that the server is running (starts it if not) and opens the panel in your browser.

![The panel opened in the browser](../img/05-app-opens-browser.jpg)

You can also go straight to the browser: **http://127.0.0.1:8765**. Switch the language with the **RU / EN** buttons in the header; the theme is on the right (light / auto / dark).

---

## Step 4. "System setup" ("Подготовка системы")

This is the first page to visit. The panel itself shows what **this** Mac is missing and installs it (every action is visible on the "Processes" tab and
recorded in the "Audit" log).

![System setup on a clean Mac](../img/06-setup-page.jpg)

| Item | What it is | How it is installed |
|---|---|---|
| **Python** | the panel's bundled Python | already installed in step 2 (checkmark) |
| **Xcode Command Line Tools** | git and build tools | the **"Install"** button → the Apple system dialog (below) |
| **Homebrew** | the package manager everything else is installed with | becomes available after Command Line Tools; official installer, macOS may ask for the administrator password |
| **Git** | included in Command Line Tools | appears after Command Line Tools |

While anything is missing, **a blue banner appears at the top of every page** saying "Missing: … System setup →" (visible in the screenshots below).

### 4.1. Command Line Tools

Click **"Install"**: the panel runs `xcode-select --install`, and macOS shows **its own** dialog. Click **Install** (and **Agree** if it asks about the license),
then wait for it to finish — the panel waits by itself, and the status is visible in "Processes".

![Apple system dialog for Command Line Tools](../img/13-clt-apple-dialog.jpg)

**Verified on a real system — two typical obstacles:**

1. **"Can’t download the software because of a network problem".** If **VPN** with a default route is enabled on the Mac, the virtual machine (and
   some other environments) has no internet; on a real Mac this error can occur when Apple's servers are blocked. Turn off the VPN and try again.
2. **"Can’t install the software because there is not enough disk space. 24.27 GB is needed but only 18.49 GB is available."** Apple's installer requires
   **about 24 GB of free space** (the package itself is under 1 GB, but Apple's check is conservative). This is exactly the warning the panel shows under the item.

   ![Apple: not enough space to install](../img/20-clt-not-enough-space.jpg)

   **What to do:** free up space (you need ≥ 25 GB) — **or** install Command Line Tools from Terminal via `softwareupdate` (the 24 GB check does not apply there; you need ~1–3 GB;
   **the administrator password is required**):
   ```bash
   sudo touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
   softwareupdate -l                                   # find the line "Label: Command Line Tools for Xcode …"
   sudo softwareupdate -i "Command Line Tools for Xcode 26.5-26.5" --verbose   # substitute your own Label
   sudo rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
   ```
   In the clean-VM check this took about 4 minutes (download ~0.9 GB + installation). The panel will see the result by itself: the item gets a checkmark after "Check again".

After Command Line Tools are installed, **Git** and **Python** are marked automatically, and only Homebrew remains:

![System setup: Command Line Tools and Git are ready, Homebrew shows "Install"](../img/21-setup-after-clt.jpg)

### 4.2. Homebrew

Click **"Install"** next to Homebrew. The panel downloads the **official installer**, shows its checksum in the log, and starts the installation
(macOS may ask for the administrator password — enter it in the macOS system dialog; the panel never sees it). Progress is visible on the "Processes" tab; in the clean-VM check
Homebrew 7.0.9 took about 3.5 minutes to install.

![System setup: all four items are ready](../img/22-setup-all-ok.jpg)

---

---

## Step 5. What next: an overview of the pages

| Page | What it is for |
|---|---|
| **Dashboard** | CPU/RAM load, temperature, disk, battery |
| **Profiles** ("Профили установки") | toolsets (Foundation, AI, Flutter, iOS, Backend): the panel shows what is already there and installs what is missing |
| **AI access** ("AI-доступ") | AI agents (Claude Code, Codex…) over MCP: registration, levels L1–L3, approval queue |
| **Virtual machines** ("Виртуальные машины") | tart, disposable VMs, and CI runners (**tart is optional** — without it the page simply says "tart not found") |
| **Backups** ("Резервные копии") | git repositories and data to a local folder or an external drive |
| **Audit** ("Аудит") | a log of everything the panel did (without passwords and tokens) |

![Dashboard](../img/07-page-dashboard.jpg)

![Profiles](../img/08-page-profiles.jpg)

![AI access](../img/09-page-connect.jpg)

![Virtual machines: tart is not found on a clean Mac — this is normal](../img/10-page-vms.jpg)

![Backups](../img/11-page-backups.jpg)

![Audit](../img/12-page-audit.jpg)

### 5.1. Profiles (verified on a clean VM)

The **"Install Profiles"** page shows toolsets and which of their tools are already present. Click **"Install everything missing"** ("Поставить всё недостающее") on a profile — the panel installs what is missing through Homebrew,
**takes a snapshot of the machine's state before and after**, and shows the result. In the check, the **"Foundation"** profile (8 missing tools: Python 3.12, gh, fzf, yq, ripgrep, lazygit, lazydocker, git-delta)
installed in about 2.5 minutes; afterwards it showed "12/12 installed".

![The "Foundation" profile: 12 of 12 installed](../img/23-profiles-installed.jpg)

The **"Snapshots"** page now holds two snapshots — "before" and "after" (Homebrew formulae: 0 → 20); you can compare them to see exactly what changed. A snapshot does not change anything in the system.

![Snapshots before and after installing the profile](../img/24-snapshots-before-after.jpg)

Next:
* connect an AI agent — `connect-ai-agent.md`;
* run CI runners in disposable VMs — `ci-runners.md`.

---

## If something goes wrong

| Symptom | What to do |
|---|---|
| `./install.sh`: "Permission denied" | `chmod +x install.sh uninstall.sh fetch-python.sh` and try again |
| installer: "could not reach the GitHub API" / "download failed" | there is no internet or it is restricted (VPN/proxy); try again — the installation is idempotent |
| "checksum mismatch" | the download was corrupted; try again. The installation **stops** and installs nothing with a wrong checksum |
| the app says the server is not responding | open the log `~/.service-admin/logs/server.err`; if there is a folder-access dialog, click "Allow" |
| port 8765 is busy | `lsof -i tcp:8765`; the panel can be started on another port: `~/.service-admin/runtime/python/bin/python3 server.py --port 8766` |
| Apple: "not enough disk space. 24.27 GB is needed…" | free up ≥ 25 GB or install Command Line Tools via `softwareupdate` (step 4.1) |
| Apple: "Can’t download the software because of a network problem" | turn off the VPN (virtual machines have no internet because of a VPN), check your network, and try again |

## Updating and uninstalling

* **Update:** replace the project folder with the new version and run `./install.sh` again — it is idempotent (it rebuilds the app, restarts the server, and does not touch your data).
* **Uninstall:** `./uninstall.sh` — removes the autostart and deletes the app. Your **data** (`~/.service-admin`: snapshots, backups, the log, agent tokens) stays; delete it manually if you do not need it:
  ```bash
  rm -rf ~/.service-admin
  ```

---

*How this document was made:* exactly these steps were run on a clean VM; the screenshots are the VM window captured from the host. What cannot be verified in the VM (the administrator password dialog, installing CLT when disk space is short) is
marked in the text and in `../../docs/en/unverified.md`.
