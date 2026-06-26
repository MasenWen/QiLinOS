#!/usr/bin/bash
#打包前1、gpg --gen-key；2、修改源码main、以及文件changlog以及control文件内版本；3、更改该文件version，与changlog对应；
version="1.0.0-ok1"
basedir=$(cd `dirname $0`; pwd)
cd $basedir
echo "check and install dependencies..."
deps=(debhelper build-essential g++ cmake qtbase5-dev qt5-qmake qttools5-dev qttools5-dev-tools libkysdk-applications-dev debmake)
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

cd $basedir/../..
rm -f kylin-actuator_${version}_amd64.deb
rm -rf kylin-actuator_${version}
cd $basedir/..
debuild --no-tgz-check --compression=xz
cd ..
dpkg-deb -R kylin-actuator_${version}_amd64.deb kylin-actuator_${version}/
dpkg-deb -Zxz -b kylin-actuator_${version} kylin-actuator_${version}_amd64.deb
rm -rf kylin-actuator_${version}
read -n1 -s -p "make deb finished, Press any key to quit..."
echo
