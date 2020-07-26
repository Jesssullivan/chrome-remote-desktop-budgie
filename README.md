
#### Fully automated patching for Chrome Remote Desktop on Ubuntu Budgie.


Chrome remote desktop is fantastic, but often clashes with Xorg nuances from a variety of desktop environments in Ubuntu.  This `chrome-remote-desktop` script extends and replaces the version automatically installed by Google in `/opt/google/chrome-remote-desktop/chrome-remote-desktop`. This stuff is only relevant for accessing your Ubuntu machine from elsewhere *(e.g. the "server", the client machine should not be installing anything, all it needs is a web browser)*.



***Set up the server:***

Before patching anything or pursuing other forms of delightful tomfoolery, follow the [installation instructions provided by Google](https://remotedesktop.google.com/access/).  Set up everything normally- install Google's .deb download with dpkg, set up a PIN, etc.   
The trouble comes when you are trying to remote in- some problems you may encounter include:
- none of the X sessions work, each immediately closing the connection to the client
- the remote desktop environment crashes or becomes mangled
- odd scaling issues or flaky resolution changes


***Patch it up:***

```
# get this script:
wget https://raw.githubusercontent.com/Jesssullivan/chrome-remote-desktop-budgie/master/chrome-remote-desktop

# or:
git clone https://github.com/Jesssullivan/chrome-remote-desktop-budgie/ 
cd chrome-remote-desktop-budgie 

# behold:
python3 chrome-remote-desktop

# ...perhaps, if you are keen (optional):
# sudo chmod u+x addsystemd.sh
# sudo ./addsystemd.sh
```

***What does this do?***

We are primarily just enforcing the use of existing instances of X and correct display values as reported by your system.

- This version keeps a persistent version itself in `/usr/local/bin/` in addition updating the one executed by Chrome in `/opt/google/chrome-remote-desktop/`.        
- A mirror of this script is also maintained at `/usr/local/bin/chrome-remote-desktop.github`, and will let the user know if there are updates.   
- The version distributed by google is retained in `/opt/` too as `chrome-remote-desktop.verbatim`.   
- Each of these versions are compared by md5 hash- this way our patched version of `chrome-remote-desktop` will always make sure it is where it should be, even after Google pushes updates and overwrites everything in `/opt/`.

