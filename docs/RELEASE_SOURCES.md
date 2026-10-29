# Release sources

Where every third-party file used by VASYA GNS LAB comes from. This page is generated from
`src/vasya/data/third_party.lock` by `scripts/lock_report.py`; edit the lock, not this page.

* **VERIFIED**: the file was downloaded from the URL on the date shown and its SHA-256 matched.
* **UNVERIFIED**: the URL could not be checked (see the reason). The installer still downloads it and
  still refuses any file whose SHA-256 differs from the pin; if no URL works the device is shown as
  "image not available".

## GNS3 server

Release packages ship GNS3 server 2.2.61 from PyPI (`gns3-server==2.2.61`), source
https://github.com/GNS3/gns3-server/tree/v2.2.61, with the patches in `src/vasya/data/patches/`.

## Appliance files

`src/vasya/data/appliances/` = https://github.com/GNS3/gns3-registry at commit
`0c04ba6100a2fed7f25d9bac5fc289d836db27fa` (unmodified). `packaging/payload/appliances/ntopng/ntopng.gns3a`
comes from commit `8ce90a6a35aaddb85bb10413a46fdf98f0993023`.

Lock generated: 2026-10-29

## Helper programs (Linux x86_64, downloaded when not installed)

| Program | Version | License | Package URL | Package SHA-256 | Source package | Source SHA-256 | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dynamips | 0.2.25 | GPL-2.0-or-later | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/d/dynamips/dynamips_0.2.25-1%7Enoble1_amd64.deb | `2fcfa4de8a0632709a8f7ab834036b34e1ef3e0bc450618e0b9539b539b45053` | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/d/dynamips/dynamips_0.2.25-1%7Enoble1.tar.gz | `62f579b736bee1a6f0f2d7134278eef337c928f6b1ce18fe70e38c63965a0cca` | VERIFIED (2026-10-29) |
| ubridge | 1.0.1 | GPL-3.0-or-later | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/u/ubridge/ubridge_1.0.1-1%7Enoble1_amd64.deb | `4c2535fb7893f8a756801cb584a770f581ca5efc25c1f75af025c01076fcc67b` | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/u/ubridge/ubridge_1.0.1-1%7Enoble1.tar.gz | `761d75c743eb9fe8a7320d7a6412bb3db615ca8d0ce893a460b905d0c0e488d2` | VERIFIED (2026-10-29) |
| vpcs | 0.8.5 | BSD-2-Clause AND ISC | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/v/vpcs/vpcs_0.8.5-1%7Enoble2_amd64.deb | `4d6ee5f55dce25689b092107ba9d045107d33c9d0b34ec4c0afd29c7ca9c1a13` | https://ppa.launchpadcontent.net/gns3/ppa/ubuntu/pool/main/v/vpcs/vpcs_0.8.5-1%7Enoble2.tar.gz | `6802e3719d3853d7de2723a49e1c6e7f19dd3876c4eea0d89e5b7b496c95ab72` | VERIFIED (2026-10-29) |

## Qt platform libraries (downloaded when missing)

| Library | Package | Version | License | URL | SHA-256 | Status |
| --- | --- | --- | --- | --- | --- | --- |
| libxcb-cursor.so.0 | libxcb-cursor0 | 0.1.4-1build1 | MIT (X11) | https://archive.ubuntu.com/ubuntu/pool/universe/x/xcb-util-cursor/libxcb-cursor0_0.1.4-1build1_amd64.deb | `137cf52479b5a9d8c5926d70d311af04be41941a32ee777340d704cc458c06d8` | VERIFIED (2026-10-29) |
| libxcb-icccm.so.4 | libxcb-icccm4 | 0.4.1-1.1build3 | MIT (X11) | https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build3_amd64.deb | `9e0e349f3904cd5bc07fea45498c4d03527a5d1178edd78555e84fdbd3793708` | VERIFIED (2026-10-29) |
| libxcb-keysyms.so.1 | libxcb-keysyms1 | 0.4.0-1build4 | MIT (X11) | https://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build4_amd64.deb | `6c261aae923175b88a032018c530873ffb40f2bf96b045fdda42bd8bc74cb1c3` | VERIFIED (2026-10-29) |

## Device images (public, downloaded from the publisher)

| File | Devices | URL | Content SHA-256 | Status |
| --- | --- | --- | --- | --- |
| CentOS-7-x86_64-GenericCloud-2111.qcow2 | centos-cloud | https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-2111.qcow2 | `4c34278cd7ba51e47d864a5cb34301a2ec7853786cb73877f3fe61bb1040edd4` | VERIFIED (2026-10-29) |
| Express-3.1-x86_64.iso | smoothwall | https://sourceforge.net/projects/smoothwall/files/SmoothWall/3.1/Express-3.1-x86_64.iso/download | `1d5664cde795d0028c2c8b5c261af5d8032da360b7954d5381beb7de63923219` | VERIFIED (2026-10-29) |
| Fedora-Cloud-Base-35-1.2.x86_64.qcow2 | fedora-cloud | https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/35/Cloud/x86_64/images/Fedora-Cloud-Base-35-1.2.x86_64.qcow2 | `fe84502779b3477284a8d4c86731f642ca10dd3984d2b5eccdf82630a9ca2de6` | VERIFIED (2026-10-29) |
| bird-tinycore64-1.5.0.img | bird | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/bird-tinycore64-1.5.0.img | `92931e34fb40618250a012204914e3ab0dc55af75f86656258c463329ef33631` | VERIFIED (2026-10-29) |
| centos-cloud-init-data.iso | centos-cloud | https://github.com/asenci/gns3-centos-cloud-init-data/raw/master/centos-cloud-init-data.iso | `9e3f50f66b0ceb5e94cebfa44a9ae98956f767dde1b2b743c76c460f4d94794c` | VERIFIED (2026-10-29) |
| chr-7.1rc7.img | mikrotik-chr | https://download.mikrotik.com/routeros/7.1rc7/chr-7.1rc7.img.zip | `8642d6da774a8020e27eb9f01b610cf0ad7dc83e254cb6cdbc1997c938be161b` | VERIFIED (2026-10-29) |
| core-linux-6.4-internet-0.1.img | internet | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/core-linux-6.4-internet-0.1.img | `39be935d68331bbd3389665bdc3809e050da6d5d02a64789138aadb39f5ba2a1` | VERIFIED (2026-10-29) |
| empty8G.qcow2 | empty-vm, ipxe | https://sourceforge.net/projects/gns-3/files/Empty%20Qemu%20disk/empty8G.qcow2/download | `878a29aee7fb08069e53f70755cecefa16182c49ec45fc7128aa4fd73531a51f` | VERIFIED (2026-10-29) |
| fedora-cloud-init-data.iso | fedora-cloud | https://raw.githubusercontent.com/GNS3/gns3-registry/master/cloud-init/fedora-cloud/fedora-cloud-init-data.iso | `fb9a03ae17c11c9a16fd6261552a581f7213d0345311b45ba1a9c4dd9b225295` | VERIFIED (2026-10-29) |
| fossapup64-9.5.iso | puppy-linux | https://distro.ibiblio.org/puppylinux/puppy-fossa/fossapup64-9.5.iso | `9f30d1c86f7e905833377b411c57866b30e59fe4535161002005bb938e8b38f5` | VERIFIED (2026-10-29) |
| frr-8.1.0.qcow2 | frr | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/frr-8.1.0.qcow2 | `c50aed102240d1788e8ecc8134d56b1ab87d5553f686e0e4c329a9fcd0be7598` | VERIFIED (2026-10-29) |
| ipcop-2.1.8-install-cd.i486.iso | IPCop | https://sourceforge.net/projects/ipcop/files/IPCop/IPCop%202.1.8/ipcop-2.1.8-install-cd.i486.iso | `ea34994ec5d9a0eff5388d9a6f3c727ebfeb547f5cad528272950c19d81f2b68` | VERIFIED (2026-10-29) |
| linux-microcore-6.4.img | microcore-linux | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/linux-microcore-6.4.img | `fa2e24710e1f4879e2e756c243b9721c5745990c7fa4b909dfb3f340feba92aa` | VERIFIED (2026-10-29) |
| linux-tinycore-6.4-2.img | tinycore-linux | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/linux-tinycore-linux-6.4-2.img | `398c2c6738b0b4d7b25a801ee08d3b4bc0c1e928d262b432dd03015ea87ecaef` | VERIFIED (2026-10-29) |
| linux-tinycore-linux-6.4-firefox-33.1.1-2.img | firefox | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/linux-tinycore-linux-6.4-firefox-33.1.1-2.img | `f08bad4a53b41dc131676b1366f3ae540b8d22099316c5935eeff9bbbc4d6261` | VERIFIED (2026-10-29) |
| mininet-vm-x86_64.vmdk | mininet | https://github.com/mininet/mininet/releases/download/2.2.2/mininet-2.2.2-170321-ubuntu-14.04.4-server-amd64.zip | `de1032fe84bdfa0de70355cae2fa5259ded6f46499540874368f79544ef0e84f` | VERIFIED (2026-10-29) |
| openbsd-5.8.qcow2 | openbsd | https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/openbsd-5.8.qcow2 | `fe0e6c599c9565fc9597f6ab473bd2a5575ab95176e80e9c141efb4c5968a9ba` | VERIFIED (2026-10-29) |
| openwrt-15.05.1-realview-vmlinux-initramfs.elf | openwrt-realview | https://downloads.openwrt.org/chaos_calmer/15.05.1/realview/generic/openwrt-15.05.1-realview-vmlinux-initramfs.elf | `d3a01037f33e7512d46d50975588d5c3a0e0cbf25f37afab44775c2a2be523e6` | VERIFIED (2026-10-29) |
| openwrt-19.07.7-x86-64-combined-ext4.img | openwrt | https://downloads.openwrt.org/releases/19.07.7/targets/x86/64/openwrt-19.07.7-x86-64-combined-ext4.img.gz | `2fae8ce1612d7e7ce7d9c4bd1274c17bd65b27ce135767573c3530a04746c7cc` | VERIFIED (2026-10-29) |
| ubuntu-20.04-server-cloudimg-amd64.img | ubuntu-cloud | https://cloud-images-archive.ubuntu.com/releases/focal/release-20210119.1/ubuntu-20.04-server-cloudimg-amd64.img | `c2d26335116d2bc00c1201330cbb95300b796e1477cf671f13adcfac77a58cd7` | UNVERIFIED (2026-10-29): https://cloud-images-archive.ubuntu.com/releases/focal/release-20210119.1/ubuntu-20.04-server-cloudimg-amd64.img: curl rc 35; https://cloud-images.ubuntu.com/releases/focal/release-20210119.1/ubuntu-20.04-server-cloudimg-amd64.img: curl rc 22 |
| ubuntu-cloud-init-data.iso | ubuntu-cloud | https://github.com/asenci/gns3-ubuntu-cloud-init-data/raw/master/ubuntu-cloud-init-data.iso | `42ad4c13c545cda0bbad46e6f645a7baa3a4c8e60790d5978d1cf3456bd022bb` | VERIFIED (2026-10-29) |
| vRIN-0.9.2.qcow2 | vrin | https://sourceforge.net/projects/vrin/files/vRIN-0.9.2.qcow2.bz2/download | `78fd8146f326d4ee9270e9607a77ed542dc36ecef9060ace39f67291eb9e3002` | VERIFIED (2026-10-29) |

## Docker images (pulled by digest)

| Image | Pinned reference | Image ID | Status |
| --- | --- | --- | --- |
| adosztal/aaa:latest | `docker.io/adosztal/aaa@sha256:a26da0b608e49ff0e75d1ec3c470efd1010a8100385129ec06aa56c3423ba568` | `sha256:6e12e40960833fd18e71b32a4c271665709c67d27dacf9a1b1863b7b2bdd84ce` | VERIFIED (2026-10-29) |
| adosztal/dns:latest | `docker.io/adosztal/dns@sha256:b25e555b778b641631e3d146f61c83808e507f9cf35a6ec8511d8f7a6fad8e1a` | `sha256:37cec4f09c83c2c539cf8146df9baa6401657c81d59d474e02043d672f6a9608` | VERIFIED (2026-10-29) |
| adosztal/net_toolbox:latest | `docker.io/adosztal/net_toolbox@sha256:5c7999be58d568e9182440fff471fc24d1c59c8b7f66ccfa545b492681d5ffd3` | `sha256:03f6cdd181885abf12ca0d860e3706e786790f69d986df64780407bc067f83c3` | VERIFIED (2026-10-29) |
| adosztal/network_automation:latest | `docker.io/adosztal/network_automation@sha256:ebd79da9ff5ced04e0d673d1a2fdc187e2caefe1c50fa3b1fa9d1ea76a7ea951` | `sha256:dd6864157ed44c1f44aa6dfaaaa292e7618af7171c15d8ab2af3e63974466796` | VERIFIED (2026-10-29) |
| adosztal/python-go-perl-php:latest | `docker.io/adosztal/python-go-perl-php@sha256:f3c920015aa2d3f1e659108d61d2c5c70a94b49a79f218cf6538a69be3de313f` | `sha256:44b142b3832abb532b5e6893e7d2d1d32c8ffc585c84336201c51877b55066d4` | VERIFIED (2026-10-29) |
| alpine | `docker.io/library/alpine@sha256:c26612752c78b18faacd63c7d50f4592c2e7b0f25e0e20e82bd74e465c57ab0d` | `sha256:b92841763c5c2140a20eeb2a44e94ebb0e80fd51d9d6b5895ea72fa999525d68` | VERIFIED (2026-10-29) |
| ghcr.io/pantheontech/stonework | `ghcr.io/pantheontech/stonework@sha256:e14ca1ceb58ba0960abb21d90beb82ddfd49e4790a1e57096e9bc35620cd9fd3` | `sha256:40c3e03603b1df33429f5902f6adec50b2c19d8039c19743a06fb9cd5f18fec9` | VERIFIED (2026-10-29) |
| gns3/chromium:latest | `docker.io/gns3/chromium@sha256:4c257748ae9b13509a79954ec455fb1377f309bc9680f8f91897da512e1f4462` | `sha256:c7e9ba1c656e3b50f9c33c398ff2fe2cd9360500d73bd2d64920814a5af1f9a6` | VERIFIED (2026-10-29) |
| gns3/ipterm:latest | `docker.io/gns3/ipterm@sha256:355646d78a4105739f72242d2a14455aaaaa61a14397d8a1c5ec7d8f725fe7b6` | `sha256:3c241f61fe1f14ecbb8944e8b2788a562aaa6111e01709f84938f9e958bde869` | VERIFIED (2026-10-29) |
| gns3/jupyter27:v2 | `docker.io/gns3/jupyter27@sha256:b999a7bbc511ea7cf1e9f012abcf5366fa1d4f5b8d058d7b35c22749502ed3b8` | `sha256:b6990c72819d16b4fc9af988798e26b9a081083fc37c9436d2382ff26f3a7a62` | VERIFIED (2026-10-29) |
| gns3/jupyter:v2 | `docker.io/gns3/jupyter@sha256:051f2c8d40d291b41cbbb3abf241eca244bfa808530adc786922a9b617e642b3` | `sha256:2553fe2f7146a6663fc16cadfa79b2646bf4fe89f728420e517ef3fa95870a72` | VERIFIED (2026-10-29) |
| gns3/kalilinux:latest | `docker.io/gns3/kalilinux@sha256:75f5ff57f373be403565bb1aceb556e66d4b0f69b6a5243ab8c09850b3845704` | `sha256:b2295c0c4563f38b7b05a81a7c2252664fcbfc784f3ea85a4b4e0d4a02d14282` | VERIFIED (2026-10-29) |
| gns3/openvswitch:latest | `docker.io/gns3/openvswitch@sha256:c2abc460f9031823312b9a34c32eb16f46fbf789853880bfafa1725355257b9a` | `sha256:47019304f918b39d87e82997da50a647e7fe766e61fe625c3c2d8c2d457145a8` | VERIFIED (2026-10-29) |
| gns3/ovs-snmp:latest | `docker.io/gns3/ovs-snmp@sha256:3c5bac1b485782496d751bc8e3330d9c76cf33f5f6c9dd937da017219a89e17b` | `sha256:01ad435c3316e80383f6a3f7bdcee3e5696a024cf41dda61ca2ee15b6db3fcb9` | VERIFIED (2026-10-29) |
| gns3/ubuntu:focal | `docker.io/gns3/ubuntu@sha256:1c6f32e4638d55fda98a4669a2cb8423c9e54d2309df5b5412c3b1f2cd968029` | `sha256:cf37c7335b09369f2d0b35f5231369af90e7bc74dea0b347ce12f11d259c2f92` | VERIFIED (2026-10-29) |
| gns3/webterm:latest | `docker.io/gns3/webterm@sha256:d36287316a24a4323364880702a8d384d84ef9d0b8096879b4664c3b1036a6ac` | `sha256:4bfd8d82003044b0ba5ef74b8990486872d72d85702c1c5420e5d1f9d35eef74` | VERIFIED (2026-10-29) |
| ntop/ntopng:latest | `docker.io/ntop/ntopng@sha256:31b58cd94dd1a96970503ed751508ec062576c006f139c74879c65df65934e48` | `sha256:9da429547b5d924cc394385c445642564eeb3995f9aa1bc7d80e001c8aaa4c1e` | VERIFIED (2026-10-29) |
| onosproject/onos:latest | `docker.io/onosproject/onos@sha256:c3d8941030a6bc8a375a49270dc3179cf1f62840b5f037c2d5e09d6dfbe55937` | `sha256:2a4338117eabe28fc488d1ae87162f97aef5e97de7becc9a774d0f4472f480fa` | VERIFIED (2026-10-29) |
| troglobit/mcjoin:latest | `docker.io/troglobit/mcjoin@sha256:169a20de1685dba32018401dd01077d65c7433fb2339b4512faa07a8143a461e` | `sha256:6491097b5fc0f249658d6ddeb5e5c6f64bd2f1ea5cadc3c12213c5d4aebd56c8` | VERIFIED (2026-10-29) |
| turnkeylinux/wordpress:latest | `docker.io/turnkeylinux/wordpress@sha256:76df05e501c774b244259f8933b5bdb7915a324b9f080f4c58d14bfc4480ea50` | `sha256:efa34a19b38599aaff1d6a0f80e8ea8e1308fccc644eb6e9bd972f7fb899bb86` | VERIFIED (2026-10-29) |

Licensed vendor images (Cisco IOS and similar) are not listed here: they are never downloaded from a public location. See [PRIVATE_IMAGES.md](PRIVATE_IMAGES.md).
