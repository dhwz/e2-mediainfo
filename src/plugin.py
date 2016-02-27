# -*- coding: utf-8 -*-
#######################################################################
# maintainer: einfall
#This plugin is free software, you are allowed to
#modify it (if you keep the license),
#but you are not allowed to distribute/publish
#it without source code (this version and your modifications).
#This means you also have to distribute
#source code of your modifications.
#######################################################################

from Components.Label import Label
from Components.ScrollLabel import ScrollLabel
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Components.config import config, getConfigListEntry, ConfigText, ConfigInteger, ConfigYesNo, ConfigSubsection, configfile
from Components.FileList import FileList
from Components.MenuList import MenuList

from Plugins.Plugin import PluginDescriptor
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from enigma import gFont, getDesktop, eTimer, eConsoleAppContainer, ePicLoad, eListboxPythonMultiContent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER, RT_WRAP
from Tools.Directories import pathExists, fileExists
from Tools.BoundFunction import boundFunction

import urllib, urllib2, re, os, time, datetime, glob, random, string
from Tools.Downloader import downloadWithProgress

from twisted.web.client import getPage, error
from twisted.internet import defer

from threading import Thread

try:
	from skin import TemplatedListFonts, componentSizes
	isDreamOS = True
except:
	isDreamOS = False

pname = "MediaInfo"
pversion = "3.0.0"

global joblist
joblist = []

global downloadsfile
downloadsfile = "/usr/lib/enigma2/python/Plugins/Extensions/mediainfo/downloads"

already_open = False
MoviePlayer.originalOpenEventView = MoviePlayer.openEventView

config.plugins.mediainfo = ConfigSubsection()
config.plugins.mediainfo.donemsg = ConfigYesNo(default = True)
config.plugins.mediainfo.origskin = ConfigYesNo(default = True)
config.plugins.mediainfo.dllimit = ConfigInteger(default = 2, limits = (1,20))
config.plugins.mediainfo.savetopath = ConfigText(default = "/media/hdd/movie/",  fixed_size=False)

class downloadTask(Thread):
	def __init__(self, session, filename, url, hoster, downloadName):
		self.session = session
		self.filename = filename
		self.url = url
		self.downloadName = downloadName
		self.hoster = hoster
		self.end = 100
		self.progress = 0
		self.recvbytes = 0
		self.totalbytes = 0
		self.path = config.plugins.mediainfo.savetopath.value
		self.local = "%s%s" % (self.path, self.filename)
		self.stop_manuell = False
		Thread.__init__(self)

	def start(self, checkname):
		if self.checkRunningJobs() < int(config.plugins.mediainfo.dllimit.value):
			print "[MediaInfo] Start Download: %s" % checkname
			agent = 'Mozilla/5.0 (Windows NT 6.1; rv:32.0) Gecko/20100101 Firefox/32.0'
			try:
				self.download = downloadWithProgress(self.url, self.local, agent=agent)
				self.download.addProgress(self.http_progress)
				self.download.start().addCallback(self.http_finished).addErrback(self.http_failed)
			except:
				print "[MediaInfo] useragent wird nicht supportet."
				self.download = downloadWithProgress(self.url, self.local)
				self.download.addProgress(self.http_progress)
				self.download.start().addCallback(self.http_finished).addErrback(self.http_failed)
			return True
		else:
			print "[MediaInfo] Max Download Slots Full %s" % checkname
			return False

	def startNextJob(self):
		print "[MediaInfo] Check for Next Download."
		if self.checkRunningJobs() < int(config.plugins.mediainfo.dllimit.value):
			global joblist
			if len(joblist) > 0:
				for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
					if status == "Wait" and self.checkRunningJobs() < int(config.plugins.mediainfo.dllimit.value):
						if job.start(filename):
							print "mark as download", filename
							self.markJobAsDownload(filename)

	def checkRunningJobs(self):
		global joblist
		countRuningJobs = 0
		if len(joblist) > 0:
			for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
				if status == "Download":
					countRuningJobs += 1
		return countRuningJobs

	def markJobAsDownload(self, change_filename):
		joblist_tmp = []
		global joblist
		if len(joblist) > 0:
			for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
				if filename == change_filename:
					joblist_tmp.append((filename, int(time.time()), "Download", url, hoster, downloadName, job))
				else:
					joblist_tmp.append((filename, starttime, status, url, hoster, downloadName, job))
			joblist = joblist_tmp

	def markJobAsFinish(self, change_filename):
		joblist_tmp = []
		global joblist
		if len(joblist) > 0:
			for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
				if filename == change_filename:
					joblist_tmp.append((filename, starttime, "Complete", url, hoster, downloadName, job))
				else:
					joblist_tmp.append((filename, starttime, status, url, hoster, downloadName, job))
			joblist = joblist_tmp

	def markJobAsError(self, change_filename):
		joblist_tmp = []
		global joblist
		if len(joblist) > 0:
			for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
				if filename == change_filename:
					joblist_tmp.append((filename, starttime, "Error", url, hoster, downloadName, job))
				else:
					joblist_tmp.append((filename, starttime, status, url, hoster, downloadName, job))
			joblist = joblist_tmp
			self.backupJobs()

	def stop(self):
		self.stop_manuell = True
		if self.download:
			self.download.stop()

	def http_progress(self, recvbytes, totalbytes):
		self.progress = int(self.end*recvbytes/float(totalbytes))
		self.recvbytes = recvbytes
		self.totalbytes = totalbytes

	def current_progress(self):
		return [self.recvbytes, self.totalbytes, self.progress]

	def http_finished(self, string=""):
		print "[http_finished]" + str(string), self.filename, self.totalbytes
		if not self.totalbytes > 250:
			self.markJobAsError(self.filename)
			self.backupJobs()
		else:
			self.markJobAsFinish(self.filename)
			self.backupJobs()
			if self.checkRunningJobs() < int(config.plugins.mediainfo.dllimit.value):
				self.startNextJob()
			if config.plugins.mediainfo.donemsg.value:
				message = self.session.open(MessageBox, "MediaInfo: %s Download Complete." % self.filename, MessageBox.TYPE_INFO, timeout=4)

	def http_failed(self, failure_instance=None, error_message=""):
		if error_message == "" and failure_instance is not None:
			error_message = failure_instance.getErrorMessage()
			print "[http_failed] " + error_message
			if not self.stop_manuell:
				self.markJobAsError(self.filename)

	def backupJobs(self):
		global downloadsfile
		if len(joblist) > 0:
			if fileExists(downloadsfile):
				download_file = open(downloadsfile, "w")
				for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
					download_file.write('"%s" "%s" "%s" "%s" "%s"\n' % (filename, status, url, hoster, downloadName))
				download_file.close()
		else:
			download_file = open(downloadsfile, "w").close()

class mediaInfoConfigScreen(Screen, ConfigListScreen):
	desktopSize = getDesktop(0).size()
	if desktopSize.width() >= 1920:
		skin = """
		<screen name="MediaInfo Config" title="" position="center,center" size="1920,1080" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1920,64" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;29" halign="center" valign="center" />
		  <widget name="config" position="15,64" size="1890,940" transparent="1" scrollbarMode="showOnDemand" />
		  <widget name="key_red" position="20,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="495,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="970,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="1445,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="20,1062" size="455,3" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="495,1062" size="455,3" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="970,1062" size="455,3" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="1445,1062" size="455,3" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""
	else:
		skin = """
		<screen name="MediaInfo Config" title="" position="center,center" size="1280,720" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1280,50" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="center" valign="center" />
		  <widget name="config" position="12,60" size="1256,600" transparent="1" scrollbarMode="showOnDemand" />
		  <widget name="key_red" position="12,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="329,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="646,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="963,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="12,701" size="305,2" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="329,701" size="305,2" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="646,701" size="305,2" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="963,701" size="305,2" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		if config.plugins.mediainfo.origskin.value:
			self.skinName = ''.join([random.choice(string.ascii_letters + string.digits) for n in xrange(32)])
		else:
			self.skinName = "mediaInfoConfigScreenV3"
		self.session = session

		self["actions"] = ActionMap(["MI_Actions"], {
			"ok"	:	self.ok,
			"cancel":	self.cancel,
			"red"	:	self.cancel,
			"green"	:	self.save,
			"left"	:	self.keyLeft,
			"right"	:	self.keyRight
		}, -1)

		self['key_red'] = Label("Cancel")
		self['key_green'] = Label("Save")
		self['key_yellow'] = Label()
		self['key_blue'] = Label()

		self.list = []
		self.createConfigList()
		ConfigListScreen.__init__(self, self.list)

	def createConfigList(self):
		self.setTitle(pname + " Setup " + pversion)
		self.list = []
		self.list.append(getConfigListEntry("Save Downloads to:", config.plugins.mediainfo.savetopath))
		self.list.append(getConfigListEntry("Show 'Download Complete' Message:", config.plugins.mediainfo.donemsg))
		self.list.append(getConfigListEntry("Parallel Downloads:", config.plugins.mediainfo.dllimit))
		self.list.append(getConfigListEntry("Use original MediaInfo Skin:", config.plugins.mediainfo.origskin))

	def changedEntry(self):
		self.createConfigList()
		self["config"].setList(self.list)

	def ok(self):
		ConfigListScreen.keyOK(self)
		if self['config'].getCurrent()[1] == config.plugins.mediainfo.savetopath:
			self.session.openWithCallback(self.selectedMediaFile, mediaInfoFolderScreen, config.plugins.mediainfo.savetopath.value)

	def selectedMediaFile(self, res):
		if res is not None:
			config.plugins.mediainfo.savetopath.value = res
			config.plugins.mediainfo.savetopath.save()
			configfile.save()
			self.changedEntry()

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.changedEntry()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.changedEntry()

	def save(self):
		config.plugins.mediainfo.savetopath.save()
		config.plugins.mediainfo.donemsg.save()
		config.plugins.mediainfo.dllimit.save()
		config.plugins.mediainfo.origskin.save()
		configfile.save()
		self.close()

	def cancel(self):
		self.close()

class mediaInfoFolderScreen(Screen):
	desktopSize = getDesktop(0).size()
	if desktopSize.width() >= 1920:
		skin = """
		<screen name="MediaInfo Folder" title="" position="center,center" size="1920,1080" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1920,64" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;29" halign="center" valign="center" />
		  <widget name="media" position="25,64" size="1870,64" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="left" valign="center" />
		  <widget name="folderlist" position="25,150" size="1870,840" transparent="1" scrollbarMode="showOnDemand" />
		  <widget name="key_red" position="20,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="495,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="970,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="1445,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="20,1062" size="455,3" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="495,1062" size="455,3" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="970,1062" size="455,3" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="1445,1062" size="455,3" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""
	else:
		skin = """
		<screen name="MediaInfo Folder" title="" position="center,center" size="1280,720" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1280,50" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="center" valign="center" />
		  <widget name="media" position="12,50" size="1256,50" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="left" valign="center" />
		  <widget name="folderlist" position="12,105" size="1256,550" transparent="1" scrollbarMode="showOnDemand" />
		  <widget name="key_red" position="12,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="329,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="646,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="963,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="12,701" size="305,2" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="329,701" size="305,2" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="646,701" size="305,2" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="963,701" size="305,2" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""

	def __init__(self, session, initDir, plugin_path = None):
		Screen.__init__(self, session)
		if config.plugins.mediainfo.origskin.value:
			self.skinName = ''.join([random.choice(string.ascii_letters + string.digits) for n in xrange(32)])
		else:
			self.skinName = "MediaInfoFolderV3"

		if not os.path.isdir(initDir):
			initDir = "/media/hdd/movie/"

		self["folderlist"] = FileList(initDir, inhibitMounts = False, inhibitDirs = False, showMountpoints = False, showFiles = False)
		self["media"] = Label()
		self["actions"] = ActionMap(["MI_Actions"],
		{
			"left": self.left,
			"right": self.right,
			"up": self.up,
			"down": self.down,
			"ok": self.ok,
			"green": self.green,
			"red": self.red,
			"cancel": self.red
		}, -1)
		self.setTitle(pname + " " + pversion + " - " + "Download folder selection")
		self["key_red"] = Label("Cancel")
		self["key_green"] = Label("Save")
		self["key_yellow"] = Label()
		self["key_blue"] = Label()

		self.onFirstExecBegin.append(self.updateFile)

	def red(self):
		self.close(None)

	def green(self):
		directory = self["folderlist"].getSelection()[0]
		if (directory.endswith("/")):
			self.fullpath = self["folderlist"].getSelection()[0]
		else:
			self.fullpath = self["folderlist"].getSelection()[0] + "/"
	  	self.close(self.fullpath)

	def up(self):
		self["folderlist"].up()
		self.updateFile()

	def down(self):
		self["folderlist"].down()
		self.updateFile()

	def left(self):
		self["folderlist"].pageUp()
		self.updateFile()

	def right(self):
		self["folderlist"].pageDown()
		self.updateFile()

	def ok(self):
		if self["folderlist"].canDescent():
			self["folderlist"].descent()
			self.updateFile()

	def updateFile(self):
		currFolder = self["folderlist"].getSelection()[0]
		self["media"].setText(currFolder)

class mediaInfo(Screen):
	desktopSize = getDesktop(0).size()
	if desktopSize.width() >= 1920:
		skin = """
		<screen name="MediaInfo" title="" position="center,center" size="1920,1080" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1920,64" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;29" halign="center" valign="center" />
		  <widget name="head" position="0,64" size="1920,64" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;29" halign="center" valign="center" />
		  <widget name="downloadList" position="15,150" size="1890,840" itemHeight="70" foregroundColor="#00ffffff" scrollbarMode="showOnDemand" transparent="1" />
		  <widget name="key_red" position="20,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="495,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="970,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="1445,1030" size="455,30" transparent="1" font="Regular;27" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="20,1062" size="455,3" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="495,1062" size="455,3" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="970,1062" size="455,3" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="1445,1062" size="455,3" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""
	else:
		skin = """
		<screen name="MediaInfo" title="" position="center,center" size="1280,720" flags="wfNoBorder">
		  <widget render="Label" source="Title" position="0,0" size="1280,50" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="center" valign="center" />
		  <widget name="head" position="0,50" size="1280,50" foregroundColor="#00ffffff" transparent="0" zPosition="5" font="Regular;26" halign="center" valign="center" />
		  <widget name="downloadList" position="12,115" size="1256,550" itemHeight="50" foregroundColor="#00ffffff" scrollbarMode="showOnDemand" transparent="1" />
		  <widget name="key_red" position="12,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_green" position="329,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_yellow" position="646,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <widget name="key_blue" position="963,674" size="305,25" transparent="1" font="Regular;22" valign="center" halign="center" zPosition="5" />
		  <eLabel name="button red" position="12,701" size="305,2" backgroundColor="#00f23d21" zPosition="5" />
		  <eLabel name="button green" position="329,701" size="305,2" backgroundColor="#0031a500" zPosition="5" />
		  <eLabel name="button yellow" position="646,701" size="305,2" backgroundColor="#00e5b243" zPosition="5" />
		  <eLabel name="button blue" position="963,701" size="305,2" backgroundColor="#000064c7" zPosition="5" />
		</screen>"""

	if isDreamOS:
		SKIN_COMPONENT_KEY = "MediaInfoList"
		SKIN_COMPONENT_PROGRESS_HEIGHT = "progressHeight"
		SKIN_COMPONENT_PROGRESS_WIDTH = "progressWidth"
		SKIN_COMPONENT_STATUS_WIDTH = "statusWidth"
		SKIN_COMPONENT_MBINFO_WIDTH = "mbinfoWidth"
		SKIN_COMPONENT_DLINFO_WIDTH = "dlinfoWidth"
		SKIN_COMPONENT_PROGRESSINFO_WIDTH = "progressinfoWidth"
		SKIN_COMPONENT_SPACER_WIDTH = "spacerWidth"

	def ListEntry(self, entry):
		desktopSize = getDesktop(0).size()
		if desktopSize.width() == 3840:
			sizefactor = 7
			zoomfactor = 2.7
		elif desktopSize.width() == 1920:
			sizefactor = 3
			zoomfactor = 1.3
		else:
			sizefactor = 1
			zoomfactor = 1

		listWidth = self['downloadList'].instance.size().width()
		itemHeight = self['downloadList'].l.getItemSize().height()
		textHeight = itemHeight/2
		self.ml.l.setItemHeight(itemHeight)
		if isDreamOS:
			sizes = componentSizes[mediaInfo.SKIN_COMPONENT_KEY]
			progressHeight = sizes.get(mediaInfo.SKIN_COMPONENT_PROGRESS_HEIGHT, 16*zoomfactor)
			progressHPos = (textHeight-progressHeight)/2
			progressWidth = sizes.get(mediaInfo.SKIN_COMPONENT_PROGRESS_WIDTH, 128*zoomfactor)
			statusWidth = sizes.get(mediaInfo.SKIN_COMPONENT_STATUS_WIDTH, 144*zoomfactor)
			mbinfoWidth = sizes.get(mediaInfo.SKIN_COMPONENT_MBINFO_WIDTH, 208*zoomfactor)
			dlinfoWidth = sizes.get(mediaInfo.SKIN_COMPONENT_DLINFO_WIDTH, 128*zoomfactor)
			progressinfoWidth = sizes.get(mediaInfo.SKIN_COMPONENT_PROGRESSINFO_WIDTH, 64*zoomfactor)
			spacerWidth = sizes.get(mediaInfo.SKIN_COMPONENT_SPACER_WIDTH, 8*zoomfactor)
			tlf = TemplatedListFonts()
			self.ml.l.setFont(0, gFont(tlf.face(tlf.MEDIUM), tlf.size(tlf.MEDIUM)))
		else:
			progressHeight = 16*zoomfactor
			progressHPos = (textHeight-progressHeight)/2
			progressWidth = 128*zoomfactor
			statusWidth = 144*zoomfactor
			mbinfoWidth = 208*zoomfactor
			dlinfoWidth = 128*zoomfactor
			progressinfoWidth = 64*zoomfactor
			spacerWidth = 8*zoomfactor
			self.ml.l.setFont(0, gFont('Regular', textHeight - 2 * sizefactor))

		(filename, status, progress, dlspeed, currentSizeMB, totalMB) = entry
		if status == "Download":
			mbinfo = "%s MB/%s MB" % (str(currentSizeMB), str(totalMB))
			dlinfo = "%s" % dlspeed
			prog = int(progress)
			proginfo = str(progress)+"%"
		elif status == "Complete":
			mbinfo = ""
			dlinfo = ""
			prog = 100
			proginfo = "100%"
		else:
			mbinfo = ""
			dlinfo = ""
			prog = 0
			proginfo = "0%"

		return [entry,
		(eListboxPythonMultiContent.TYPE_TEXT, 0, 0, listWidth-progressWidth-progressinfoWidth-statusWidth-3*spacerWidth, itemHeight, 0, RT_HALIGN_LEFT | RT_WRAP, filename),
		(eListboxPythonMultiContent.TYPE_PROGRESS, listWidth-progressWidth-progressinfoWidth-statusWidth-2*spacerWidth, progressHPos, progressWidth, progressHeight, prog),
		(eListboxPythonMultiContent.TYPE_TEXT, listWidth-progressinfoWidth-statusWidth-spacerWidth, 0, progressinfoWidth, textHeight, 0, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, proginfo),
		(eListboxPythonMultiContent.TYPE_TEXT, listWidth-statusWidth, 0, statusWidth, textHeight, 0, RT_HALIGN_CENTER | RT_VALIGN_CENTER, status),
		(eListboxPythonMultiContent.TYPE_TEXT, listWidth-progressWidth-progressinfoWidth-statusWidth-2*spacerWidth, textHeight, mbinfoWidth, textHeight, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, mbinfo),
		(eListboxPythonMultiContent.TYPE_TEXT, listWidth-dlinfoWidth, textHeight, dlinfoWidth, textHeight, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, dlinfo),
		]

	def __init__(self, session, livestreaming):
		Screen.__init__(self, session)
		if config.plugins.mediainfo.origskin.value:
			self.skinName = ''.join([random.choice(string.ascii_letters + string.digits) for n in xrange(32)])
		else:
			self.skinName = "mediaInfoV3"
		self.session = session

		self['head'] = Label()
		self['key_red'] = Label("Remove")
		self['key_green'] = Label("Download")
		self['key_yellow'] = Label("Start/Stop")
		self['key_blue'] = Label("Setup")

		global joblist
		self.dllist = []
		self.ml = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
		self['downloadList'] = self.ml

		self["actions"]  = ActionMap(["MI_Actions"], {
			"ok"	:	self.exit,
			"info"	:	self.exit,
			"cancel":	self.exit,
			"back"	:	self.exit,
			"red"	:	self.jobRemove,
			"green"	:	self.jobStart,
			"yellow":	self.jobCheck,
			"blue"	:	self.mediaInfoSetup
		}, -1)

		self.refreshTimer = eTimer()
		self.setTitle(pname + " " + pversion)
		if isDreamOS:
			self.refreshTimer_conn1 = self.refreshTimer.timeout.connect(self.showJobs)
		else:
			self.refreshTimer.callback.append(self.showJobs)
		self.refreshTimer.start(1000)
		self.onLayoutFinish.append(self.showJobs)

	def jobStart(self):
		service = self.session.nav.getCurrentService()
		filename = service.info().getName()
		url = self.session.nav.getCurrentlyPlayingServiceReference().getPath()
		filename = ''.join(re.split(r'[.;:!&?,]', filename))
		quessFileType = os.path.splitext(url)[1][1:]
		if re.search('(\.avi|\.mp4|\.ts|\.flv|\.mp3|\.mpg|\.mpeg|\.mkv)', quessFileType, re.I):
			filetype = quessFileType
		else:
			filetype = ".mp4"
		filename = "%s%s" % (filename.replace(' ','_'), filetype)

		if not any(filename in job for job in joblist):
			if re.match('.*?http', url, re.S) and not re.match('.*?m3u8', url, re.S):
				try:
					req = urllib2.Request(url, headers={'Content-Type':'application/x-www-form-urlencoded', 'User-agent':'Mozilla/5.0 (Windows NT 6.1; rv:32.0) Gecko/20100101 Firefox/32.0'})
					res = urllib2.urlopen(req)
					url = res.geturl()
					print "[Download] added: %s - %s" % (filename, url)
					self.addJob = downloadTask(self.session, filename, url, "stream", None)
					global joblist
					joblist.append((filename, int(time.time()), "Wait", url, "stream", None, self.addJob))
					self.jobDownload(filename)
					self.backupJobs()
				except urllib2.HTTPError, error:
					print error
					message = self.session.open(MessageBox, ("Error: %s" % error), MessageBox.TYPE_INFO, timeout=3)
				except urllib2.URLError, error:
					print error.reason
					message = self.session.open(MessageBox, ("Error: %s" % error.reason), MessageBox.TYPE_INFO, timeout=3)
			else:
				message = self.session.open(MessageBox, ("No rtmp/m3u8 download support, only http protocol."), MessageBox.TYPE_INFO, timeout=3)
		else:
			print "[MediaInfo] dupe: %s" % filename

	def showJobs(self):
		self.taskList = []
		global joblist
		showDownload = 0
		showWait = 0
		showComplete = 0
		showError = 0
		self.dllist = []
		self.waitlist = []
		self.completelist = []
		self.errorlist = []
		for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
			if status == "Download":
				showDownload += 1
				(recvbytes, totalbytes, progress) = job.current_progress()
				currentSizeMB = int(recvbytes/1024/1024)
				totalMB = int(totalbytes/1024/1024)
				dlspeed = self.calcDnSpeed(int(starttime), currentSizeMB, totalMB)
				self.dllist.append((filename, status, progress, dlspeed, currentSizeMB, totalMB))
			elif status == "Wait":
				showWait += 1
				self.waitlist.append((filename, status, 0, 0, 0, 0))
			elif status == "Complete":
				showComplete += 1
				self.completelist.append((filename, status, 0, 0, 0, 0))
			elif status == "Error":
				showError += 1
				self.errorlist.append((filename, status, 0, 0, 0, 0))
		info = "Downloads: %s/%s (%s) - Wait: %s - Complete: %s - Error: %s" % (str(showDownload), str(len(joblist)), str(config.plugins.mediainfo.dllimit.value), str(showWait), str(showComplete), str(showError))
		self["head"].setText(info)
		self.taskList = self.dllist + self.waitlist + self.completelist + self.errorlist
		self.ml.setList(map(self.ListEntry, self.taskList))

	def calcDnSpeed(self, starttime, currentSizeMB, totalMB):
		endtime = int(time.time())
		runtime = endtime - int(starttime)
		if runtime == 0:
			runtime = 1
		#if currentSizeMB == 0:
		#	currentSizeMB = 1
		dlspeed = (currentSizeMB * 1024) / runtime
		#resttime = (((int(totalMB) - currentSizeMB) * 1024) / (currentSizeMB * 1024)) * runtime
		if dlspeed > 1024:
			dlspeed = "%.2f MB/s" % (float(dlspeed) / 1024)
		else:
			dlspeed = "%s KB/s" % dlspeed
		return dlspeed

	def jobCheck(self):
		exist = self['downloadList'].getCurrent()
		if exist == None:
			return
		filename = self['downloadList'].getCurrent()[0][0]
		status = self['downloadList'].getCurrent()[0][1]
		if status == "Download":
			self.jobStop(filename, False)
		else:
			self.jobDownload(filename)

	def jobDownload(self, change_filename):
		global joblist
		for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
			if filename == change_filename:
				if hoster == "stream":
					if job.start(filename):
						job.markJobAsDownload(filename)
		self.showJobs()

	def jobStop(self, change_filename, remove=False):
		joblist_tmp = []
		global joblist
		for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
			if filename == change_filename:
				job.stop()
				if not remove:
					joblist_tmp.append((filename, starttime, "Wait", url, hoster, downloadName, job))
			else:
				joblist_tmp.append((filename, starttime, status, url, hoster, downloadName, job))
		joblist = joblist_tmp
		self.showJobs()

	def jobRemove(self):
		exist = self['downloadList'].getCurrent()
		if exist == None:
			return
		check_filename = self['downloadList'].getCurrent()[0][0]
		check_status = self['downloadList'].getCurrent()[0][1]
		if check_status == "Download":
			self.jobStop(check_filename, True)
			self.showJobs()
		elif check_status == "Wait" or "Complete" or "Error":
			joblist_tmp = []
			global joblist
			for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
				if not filename == check_filename:
					joblist_tmp.append((filename, starttime, status, url, hoster, downloadName, job))
			joblist = joblist_tmp
			self.showJobs()
			self.backupJobs()

	def backupJobs(self):
		global downloadsfile
		if len(joblist) > 0:
			if fileExists(downloadsfile):
				download_file = open(downloadsfile, "w")
				for (filename, starttime, status, url, hoster, downloadName, job) in joblist:
					download_file.write('"%s" "%s" "%s" "%s" "%s"\n' % (filename, status, url, hoster, downloadName))
				download_file.close()
		else:
			download_file = open(downloadsfile, "w").close()

	def formatKBits(self, value, ending="Bit/s", roundNumbers=2):
		bits = value * 8
		if bits > (1024*1024):
			return str(round(float(bits)/float(1024*1024),roundNumbers))+" M"+ending
		if bits > 1024:
			return str(round(float(bits)/float(1024),roundNumbers))+" K"+ending
		else:
			return str(bits)+" "+ending

	def formatKB(self, value, ending="B", roundNumbers=2):
		byte = value
		if byte > (1024*1024):
			return str(round(float(byte)/float(1024*1024),roundNumbers))+" M"+ending
		if byte > 1024:
			return str(round(float(byte)/float(1024),roundNumbers))+" K"+ending
		else:
			return str(byte)+" "+ending

	def mediaInfoSetup(self):
		self.session.open(mediaInfoConfigScreen)

	def exit(self):
		already_open = False
		self.close()

def openMoviePlayerEventView(self):
	already_open = False
	if True and not already_open:
		already_open = True
		service = self.session.nav.getCurrentService()
		filename = service.info().getName()
		url = self.session.nav.getCurrentlyPlayingServiceReference().getPath()
		if re.match('.*?http://', url, re.S):
			self.session.open(mediaInfo, True)
		else:
			MoviePlayer.originalOpenEventView(self)
	else:
		MoviePlayer.originalOpenEventView(self)

MoviePlayer.openEventView = openMoviePlayerEventView

def autostart(reason, **kwargs):
	global downloadsfile
	if (reason == 0) and (kwargs.has_key("session")):
		session = kwargs["session"]
		global joblist
		print "[MediaInfo] READ OLD JOBS !!!"
		if fileExists(downloadsfile):
			dlfile = open(downloadsfile, "r")
			for rawData in dlfile.readlines():
				data = re.findall('"(.*?)" "(.*?)" "(.*?)" "(.*?)" "(.*?)"', rawData, re.S)
				if data:
					(filename, status, url, hoster, downloadName) = data[0]
					addJob = downloadTask(session, filename, url, hoster, downloadName)
					if status == "Download":
						joblist.append((filename, int(time.time()), "Wait", url, hoster, downloadName, addJob))
					elif status == "Error":
						joblist.append((filename, int(time.time()), "Wait", url, hoster, downloadName, addJob))
					else:
						joblist.append((filename, int(time.time()), status, url, hoster, downloadName, addJob))
		else:
			dlfile = open(downloadsfile, "w").close()

def main(session, **kwargs):
	session.open(mediaInfo, False)

def Plugins(**kwargs):
	return [PluginDescriptor(name="MediaInfo", description="Stream Downloader", where = [PluginDescriptor.WHERE_PLUGINMENU], icon="plugin.png", fnc=main),
			PluginDescriptor(where=[PluginDescriptor.WHERE_SESSIONSTART], fnc=autostart)]