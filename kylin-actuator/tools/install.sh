#!/usr/bin/bash
version="1.0.0-ok1"
basedir=$(cd `dirname $0`; pwd)
cd $basedir
echo "check and install dependencies..."
deps=(debhelper build-essential g++ cmake qtbase5-dev qt5-qmake qttools5-dev qttools5-dev-tools libkysdk-applications-dev)
apt list --installed 2> /dev/null > ./.temp
uninstalled=false
for dep in ${deps[@]}
do
	if ! grep -E ^$dep/ ./.temp
	then
		echo "$dep is not installed"
		uninstalled=true
		break
	fi
done
rm ./.temp
if $uninstalled
then
	sudo apt install -y ${deps[*]} 2> /dev/null && echo "Successfully install dependencies"
fi
cd $basedir/..
rm -rf build
mkdir build
cd build
cmake .. && make && sudo make install
read -n1 -s -p "install finished, press any key to quit..."
echo
