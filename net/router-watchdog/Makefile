include $(TOPDIR)/rules.mk

PKG_NAME:=router-watchdog
PKG_VERSION:=1.0.2
PKG_RELEASE:=1
PKG_MAINTAINER:=Arap919
PKG_LICENSE:=MIT
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/router-watchdog
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Mihomo provider failover watchdog
  DEPENDS:=+python3 +ca-bundle
  PKGARCH:=all
endef

define Package/router-watchdog/description
Cron-friendly Mihomo failover watchdog for provider-backed selector groups.
The package checks the currently selected proxy with a fresh provider healthcheck,
selects healthy candidates, benchmarks them through the local HTTP proxy and
switches the target selector to the best candidate.
endef

define Package/router-watchdog/conffiles
/opt/etc/router-watchdog.json
endef

define Package/router-watchdog/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0
/opt/bin/router-watchdog --sync-cron
endef

define Package/router-watchdog/prerm
#!/bin/sh
[ "$$1" = "upgrade" ] && exit 0
[ -n "$${IPKG_INSTROOT}" ] && exit 0
/opt/bin/router-watchdog --remove-cron
endef

define Build/Compile
	true
endef

define Package/router-watchdog/install
	$(INSTALL_DIR) $(1)/opt/bin
	$(INSTALL_DIR) $(1)/opt/libexec/router-watchdog
	$(INSTALL_DIR) $(1)/opt/etc
	$(INSTALL_DIR) $(1)/opt/etc/cron.1min

	$(INSTALL_BIN) ./files/opt/bin/router-watchdog $(1)/opt/bin/router-watchdog
	$(INSTALL_BIN) ./files/opt/libexec/router-watchdog/router_watchdog.py $(1)/opt/libexec/router-watchdog/router_watchdog.py
	$(INSTALL_CONF) ./files/opt/etc/router-watchdog.json $(1)/opt/etc/router-watchdog.json
	$(INSTALL_BIN) ./files/opt/etc/cron.1min/router-watchdog $(1)/opt/etc/cron.1min/router-watchdog
endef

$(eval $(call BuildPackage,router-watchdog))
