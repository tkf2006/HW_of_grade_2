from mininet.net import Mininet
from mininet.node import Node
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import time


class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1 >/dev/null')
        self.cmd('sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null')
        self.cmd('sysctl -w net.ipv4.conf.default.rp_filter=0 >/dev/null')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0 >/dev/null')
        super(LinuxRouter, self).terminate()


def write_frr_config(router, networks):
    conf_dir = f"/tmp/{router.name}"
    router.cmd(f"mkdir -p {conf_dir}")

    zebra_conf = f"""hostname {router.name}
password zebra
enable password zebra
log stdout
"""

    rip_conf = f"""hostname {router.name}
password zebra
enable password zebra
!
router rip
 version 2
 no auto-summary
"""

    for net in networks:
        rip_conf += f" network {net}\n"

    rip_conf += """!
log stdout
"""

    router.cmd(f"cat > {conf_dir}/zebra.conf << 'EOF'\n{zebra_conf}\nEOF")
    router.cmd(f"cat > {conf_dir}/ripd.conf << 'EOF'\n{rip_conf}\nEOF")

    router.cmd(f"chmod 777 {conf_dir}")
    router.cmd(f"chmod 644 {conf_dir}/zebra.conf")
    router.cmd(f"chmod 644 {conf_dir}/ripd.conf")

    
def start_frr(router):
    conf_dir = f"/tmp/{router.name}"

    router.cmd(f"rm -f {conf_dir}/zebra.pid {conf_dir}/ripd.pid {conf_dir}/zserv.api")

    zebra_cmd = (
        f"/usr/lib/frr/zebra "
        f"-d "
        f"-f {conf_dir}/zebra.conf "
        f"-i {conf_dir}/zebra.pid "
        f"-z {conf_dir}/zserv.api "
        f"> {conf_dir}/zebra_start.log 2>&1"
    )

    ripd_cmd = (
        f"/usr/lib/frr/ripd "
        f"-d "
        f"-f {conf_dir}/ripd.conf "
        f"-i {conf_dir}/ripd.pid "
        f"-z {conf_dir}/zserv.api "
        f"> {conf_dir}/ripd_start.log 2>&1"
    )

    router.cmd(zebra_cmd)
    time.sleep(1)
    router.cmd(ripd_cmd)
    time.sleep(1)

    z = router.cmd("pgrep -a zebra")
    r = router.cmd("pgrep -a ripd")

    if not z:
        info(f"*** {router.name} zebra 启动失败，日志如下：\n")
        info(router.cmd(f"cat {conf_dir}/zebra_start.log"))

    if not r:
        info(f"*** {router.name} ripd 启动失败，日志如下：\n")
        info(router.cmd(f"cat {conf_dir}/ripd_start.log"))

def create_topology():
    net = Mininet(link=TCLink)

    info("*** 添加 5 台路由器\n")
    r1 = net.addHost('r1', cls=LinuxRouter, ip=None)
    r2 = net.addHost('r2', cls=LinuxRouter, ip=None)
    r3 = net.addHost('r3', cls=LinuxRouter, ip=None)
    r4 = net.addHost('r4', cls=LinuxRouter, ip=None)
    r5 = net.addHost('r5', cls=LinuxRouter, ip=None)

    info("*** 创建链路\n")
    net.addLink(r1, r2, bw=10, delay='1ms')  # r1-eth0, r2-eth0
    net.addLink(r2, r3, bw=10, delay='1ms')  # r2-eth1, r3-eth0
    net.addLink(r1, r4, bw=10, delay='1ms')  # r1-eth1, r4-eth0
    net.addLink(r4, r5, bw=10, delay='1ms')  # r4-eth1, r5-eth0
    net.addLink(r2, r5, bw=10, delay='1ms')  # r2-eth2, r5-eth1
    net.addLink(r3, r5, bw=10, delay='1ms')  # r3-eth1, r5-eth2

    info("*** 启动网络\n")
    net.start()

    info("*** 配置 IP 地址\n")
    r1.cmd("ip addr add 10.0.1.1/24 dev r1-eth0")
    r1.cmd("ip addr add 10.0.4.1/24 dev r1-eth1")

    r2.cmd("ip addr add 10.0.1.2/24 dev r2-eth0")
    r2.cmd("ip addr add 10.0.2.1/24 dev r2-eth1")
    r2.cmd("ip addr add 10.0.5.1/24 dev r2-eth2")

    r3.cmd("ip addr add 10.0.2.2/24 dev r3-eth0")
    r3.cmd("ip addr add 10.0.6.1/24 dev r3-eth1")

    r4.cmd("ip addr add 10.0.4.2/24 dev r4-eth0")
    r4.cmd("ip addr add 10.0.3.1/24 dev r4-eth1")

    r5.cmd("ip addr add 10.0.3.2/24 dev r5-eth0")
    r5.cmd("ip addr add 10.0.5.2/24 dev r5-eth1")
    r5.cmd("ip addr add 10.0.6.2/24 dev r5-eth2")

    info("*** 开启接口\n")
    for r in [r1, r2, r3, r4, r5]:
        for intf in r.intfList():
            if str(intf) != 'lo':
                r.cmd(f"ip link set {intf} up")

    info("*** 生成 FRR 配置文件\n")
    write_frr_config(r1, ["10.0.1.0/24", "10.0.4.0/24"])
    write_frr_config(r2, ["10.0.1.0/24", "10.0.2.0/24", "10.0.5.0/24"])
    write_frr_config(r3, ["10.0.2.0/24", "10.0.6.0/24"])
    write_frr_config(r4, ["10.0.4.0/24", "10.0.3.0/24"])
    write_frr_config(r5, ["10.0.3.0/24", "10.0.5.0/24", "10.0.6.0/24"])

    info("*** 启动 zebra 和 ripd\n")
    for r in [r1, r2, r3, r4, r5]:
        start_frr(r)

    info("*** 等待 RIP 收敛 20 秒\n")
    time.sleep(20)

    info("*** 进入 Mininet CLI\n")
    CLI(net)

    info("*** 停止网络\n")
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    create_topology()