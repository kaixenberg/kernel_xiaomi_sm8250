// SPDX-License-Identifier: GPL-2.0
/*
 * Generic wakelock blocker, based on the Boeffla wakelock blocker driver
 * by andip71 (v1.1.0, 2017). Keeps its sysfs interface:
 *
 *   /sys/class/misc/boeffla_wakelock_blocker/wakelock_blocker
 *   /sys/class/misc/boeffla_wakelock_blocker/wakelock_blocker_default
 *   /sys/class/misc/boeffla_wakelock_blocker/debug
 *   /sys/class/misc/boeffla_wakelock_blocker/version
 *
 * Both lists are ';'-separated wakeup source names. Unlike the original,
 * the default list starts empty, so nothing is blocked until userspace
 * writes a list.
 */

#include <linux/device.h>
#include <linux/init.h>
#include <linux/miscdevice.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include <linux/sysfs.h>

#include "boeffla_wl_blocker.h"

#define BOEFFLA_WL_BLOCKER_VERSION	"1.1.0-mt"
#define LIST_WL_LEN			1024
#define LIST_WL_SEARCH_LEN		(2 * LIST_WL_LEN + 4)
/* Longest wakeup source name that can be matched */
#define WL_NAME_MAX			64

static char list_wl[LIST_WL_LEN];
static char list_wl_default[LIST_WL_LEN];
/* ";user;default;" so a name matches as ";name;" */
static char list_wl_search[LIST_WL_SEARCH_LEN];
static bool wl_blocker_active;
static bool wl_blocker_debug;
/* Taken from wakeup event paths, which may run in hard IRQ context */
static DEFINE_RAW_SPINLOCK(wl_lock);

bool boeffla_wl_blocked(const char *name)
{
	char key[WL_NAME_MAX + 3];
	unsigned long flags;
	size_t len;
	bool blocked;

	if (unlikely(READ_ONCE(wl_blocker_debug)))
		pr_info("Boeffla WL blocker: %s requested\n", name);

	if (!READ_ONCE(wl_blocker_active) || !name)
		return false;

	len = strlen(name);
	if (!len || len > WL_NAME_MAX)
		return false;

	key[0] = ';';
	memcpy(key + 1, name, len);
	key[len + 1] = ';';
	key[len + 2] = '\0';

	raw_spin_lock_irqsave(&wl_lock, flags);
	blocked = strstr(list_wl_search, key) != NULL;
	raw_spin_unlock_irqrestore(&wl_lock, flags);

	if (blocked && unlikely(READ_ONCE(wl_blocker_debug)))
		pr_info("Boeffla WL blocker: %s blocked\n", name);

	return blocked;
}

/* Called with wl_lock held */
static void build_search_string(void)
{
	scnprintf(list_wl_search, sizeof(list_wl_search), ";%s;%s;",
		  list_wl, list_wl_default);
	/* Anything beyond the bare ";;;" separators means a list is set */
	WRITE_ONCE(wl_blocker_active, strlen(list_wl_search) > 3);
}

static ssize_t store_list(char *list, const char *buf, size_t n)
{
	char tmp[LIST_WL_LEN];
	unsigned long flags;
	size_t len;

	/* Keep the first word only, as the original sscanf("%s") did */
	buf = skip_spaces(buf);
	len = strcspn(buf, " \t\n");
	if (len >= sizeof(tmp))
		return -EINVAL;
	memcpy(tmp, buf, len);
	tmp[len] = '\0';

	raw_spin_lock_irqsave(&wl_lock, flags);
	strscpy(list, tmp, LIST_WL_LEN);
	build_search_string();
	raw_spin_unlock_irqrestore(&wl_lock, flags);

	return n;
}

static ssize_t show_list(const char *list, char *buf)
{
	char tmp[LIST_WL_LEN];
	unsigned long flags;

	raw_spin_lock_irqsave(&wl_lock, flags);
	strscpy(tmp, list, sizeof(tmp));
	raw_spin_unlock_irqrestore(&wl_lock, flags);

	return scnprintf(buf, PAGE_SIZE, "%s\n", tmp);
}

static ssize_t wakelock_blocker_show(struct device *dev,
				     struct device_attribute *attr, char *buf)
{
	return show_list(list_wl, buf);
}

static ssize_t wakelock_blocker_store(struct device *dev,
				      struct device_attribute *attr,
				      const char *buf, size_t n)
{
	return store_list(list_wl, buf, n);
}

static ssize_t wakelock_blocker_default_show(struct device *dev,
					     struct device_attribute *attr,
					     char *buf)
{
	return show_list(list_wl_default, buf);
}

static ssize_t wakelock_blocker_default_store(struct device *dev,
					      struct device_attribute *attr,
					      const char *buf, size_t n)
{
	return store_list(list_wl_default, buf, n);
}

static ssize_t debug_show(struct device *dev, struct device_attribute *attr,
			  char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "Debug status: %d\nActive: %d\n",
			 READ_ONCE(wl_blocker_debug),
			 READ_ONCE(wl_blocker_active));
}

static ssize_t debug_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t n)
{
	bool val;

	if (kstrtobool(buf, &val))
		return -EINVAL;
	WRITE_ONCE(wl_blocker_debug, val);
	return n;
}

static ssize_t version_show(struct device *dev, struct device_attribute *attr,
			    char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%s\n", BOEFFLA_WL_BLOCKER_VERSION);
}

static DEVICE_ATTR_RW(wakelock_blocker);
static DEVICE_ATTR_RW(wakelock_blocker_default);
static DEVICE_ATTR_RW(debug);
static DEVICE_ATTR_RO(version);

static struct attribute *boeffla_wl_blocker_attrs[] = {
	&dev_attr_wakelock_blocker.attr,
	&dev_attr_wakelock_blocker_default.attr,
	&dev_attr_debug.attr,
	&dev_attr_version.attr,
	NULL
};

static const struct attribute_group boeffla_wl_blocker_group = {
	.attrs = boeffla_wl_blocker_attrs,
};

static const struct attribute_group *boeffla_wl_blocker_groups[] = {
	&boeffla_wl_blocker_group,
	NULL
};

static struct miscdevice boeffla_wl_blocker_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "boeffla_wakelock_blocker",
	.groups = boeffla_wl_blocker_groups,
};

static int __init boeffla_wl_blocker_init(void)
{
	int ret = misc_register(&boeffla_wl_blocker_device);

	if (ret) {
		pr_err("Boeffla WL blocker: registration failed: %d\n", ret);
		return ret;
	}

	pr_info("Boeffla WL blocker: driver version %s started\n",
		BOEFFLA_WL_BLOCKER_VERSION);
	return 0;
}
device_initcall(boeffla_wl_blocker_init);
