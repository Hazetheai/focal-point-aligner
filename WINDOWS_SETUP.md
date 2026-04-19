# Windows Setup Guide for Focal Point Aligner

This guide will help you set up and run the Focal Point Aligner app on a Windows computer, even if you've never used command-line tools before.

---

## Part 1: One-Time Setup (Do These Steps Once)

### Step 1.1: Install Git

Git is a tool that lets you download the app from the internet.

1. Open your web browser and go to: **https://git-scm.com/download/win**
2. The download should start automatically. If it doesn't, click the "64-bit Git for Windows Setup" button.
3. When the file finishes downloading, click on it to run the installer.
4. **Important:** When you see the installation options, just click "Next" and keep all the default settings. Don't change anything unless you're sure.
5. Click "Install" to begin the installation.
6. When it's done, click "Finish".

**To verify Git installed correctly:**
- Press the Windows key + R on your keyboard
- Type `cmd` and press Enter
- In the black window that appears, type: `git --version`
- Press Enter
- You should see something like `git version 2.x.x`
- Close the window by typing `exit` and pressing Enter

---

### Step 1.2: Install Miniconda

Miniconda is a tool that manages Python and the libraries the app needs. We use this instead of installing Python directly because it makes everything easier to manage.

1. Open your web browser and go to: **https://docs.anaconda.com/miniconda/**
2. Scroll down to the "Miniconda3 Installer Links" section
3. Find the Windows installer for **Python 3.11** (it will say something like "Miniconda3 Windows (64-bit) installer")
4. Click to download the `.exe` file
5. When the file finishes downloading, click on it to run the installer
6. **Important:** When you see "Add Miniconda3 to my PATH environment variable" - **do NOT check this box**. This is important!
7. Click "Next" and keep all other default settings.
8. Click "Install" to begin the installation.
9. When it's done, click "Next" then "Finish".

**To verify Miniconda installed correctly:**
- Click the Windows Start button (the Windows logo in the bottom-left corner)
- Look for "Anaconda Prompt (Miniconda3)" in the list of programs
- Click on it to open it
- You should see a window that says something like `(base) C:\Users\YourName>`
- Close the window by typing `exit` and pressing Enter

---

### Step 1.3: Download the App from GitHub

1. Open your web browser and go to: **https://github.com/Hazetheai/focal-point-aligner**
2. Look for the green button that says "Code" near the top-right of the page
3. Click the "Code" button
4. Click "Download ZIP"
5. The file `focal-point-aligner-main.zip` will download to your computer (usually to your Downloads folder)

---

### Step 1.4: Extract the ZIP File

1. Find the downloaded file `focal-point-aligner-main.zip` (check your Downloads folder)
2. Right-click on the file
3. Click "Extract All..."
4. A window will ask where you want to extract the files
5. Choose a location like `C:\Users\YourName\Documents\FocalPointAligner`
   - Replace "YourName" with your Windows username
   - Or just use your Desktop for easy access
6. Click "Extract"
7. Open the extracted folder and confirm you can see files like `README.md` and a folder called `FocalPointAligner`

**Important:** Remember where you extracted this folder! You'll need to navigate to it every time you want to run the app.

---

## Part 2: First-Time Environment Setup (Do Once Per Computer)

This step installs the Python libraries the app needs. You'll only need to do this once on each computer.

1. Click the Windows Start button
2. Search for and open "**Anaconda Prompt (Miniconda3)**"
3. A black window will open with text like `(base) C:\Users\YourName>`
4. Copy and paste this command, then press Enter:

```
conda create -n focal-align python=3.11 -y
```

5. Wait for it to finish (this may take a few minutes)
6. When you see `(base)` again, copy and paste this command and press Enter:

```
conda activate focal-align
```

7. The text should change to `(focal-align)`
8. Now copy and paste this command and press Enter:

```
pip install PyQt6>=6.9.0 opencv-python>=4.13.0 pillow>=12.0.0 numpy>=2.0.0
```

9. Wait for it to finish installing (this may take several minutes)
10. When you see `(focal-align)` again, the installation is complete!

---

## Part 3: Running the App (Do This Every Time)

### To Start the App:

1. Click the Windows Start button
2. Search for and open "**Anaconda Prompt (Miniconda3)**"
3. Type this command and press Enter:

```
conda activate focal-align
```

4. The text should change to `(focal-align)`
5. Now type this command (replacing `YourPath` with where you extracted the folder) and press Enter:

```
cd C:\Users\YourName\Documents\FocalPointAligner\focal-point-aligner-main
```

   - If you extracted to your Desktop, it would be: `cd C:\Users\YourName\Desktop\focal-point-aligner-main`
6. Now type this command and press Enter:

```
python FocalPointAligner\main.py
```

7. The Focal Point Aligner app should open!

---

## Part 4: Troubleshooting

### Problem: "conda is not recognized"

**Cause:** You opened the wrong program (regular Command Prompt instead of Anaconda Prompt)

**Solution:**
- Make sure you search for "Anaconda Prompt" in the Start menu
- Look for the icon that says "Anaconda Prompt (Miniconda3)"

---

### Problem: "pip is not recognized" or "pip install failed"

**Cause:** pip didn't install correctly or the installation was interrupted

**Solution:**
1. In Anaconda Prompt, type `conda activate focal-align` and press Enter
2. Try running the pip command again:

```
pip install PyQt6>=6.9.0 opencv-python>=4.13.0 pillow>=12.0.0 numpy>=2.0.0
```

---

### Problem: The app window opens but is blank or shows an error

**Cause:** Missing files or incorrect folder path

**Solution:**
- Make sure you're in the correct folder. Type `cd` followed by the path to where you extracted the files
- Verify the folder contains a `FocalPointAligner` subfolder with `main.py` inside it

---

### Problem: Windows SmartScreen says "Windows protected your PC"

**Cause:** The app is from an unidentified developer (which is normal for downloaded apps)

**Solution:**
- Click "More info" then "Run anyway"
- Or right-click the app file and select "Run as administrator"

---

### Problem: "No module named PyQt6" or other import errors

**Cause:** The Python libraries weren't installed correctly

**Solution:**
1. Close all Anaconda Prompt windows
2. Reopen Anaconda Prompt
3. Type `conda activate focal-align` and press Enter
4. Type `pip list` and press Enter
5. Check if PyQt6, opencv-python, pillow, and numpy are listed
6. If any are missing, run the pip install command again

---

## Need Help?

If you're still having trouble, contact the person who gave you this app and provide:
- What step you're on
- What error message you see (if any)
- What you already tried

---

## Quick Reference Card

Every time you want to use the app, just do these three steps:

```
1. Open Anaconda Prompt
2. Type: conda activate focal-align
3. Type: cd YourPathToTheApp
4. Type: python FocalPointAligner\main.py
```

Good luck!