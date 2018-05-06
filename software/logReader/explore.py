import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import urlparse
import os
import sys
import time
import json

import math

from collections import OrderedDict

import shutil

sys.path.insert(0, os.path.abspath(".."))
from . import logReader
from . import chartBuilder

class handler:
	def __init__(self, builder, *args):
		self.builder = builder
		self.label = builder.get_object("label1")
		self.grid = builder.get_object("grid1")
		self.log = builder.get_object("textview1")
		self.logScroll = builder.get_object("logScroll")
		self.modeBox = builder.get_object("modeBox")
		self.refEntry = builder.get_object("refEntry")
		self.freeCheck = builder.get_object("freeCheck")
		self.chartTitleEntry = builder.get_object("chartTitleEntry")
		self.refPath = ''
		self.fileList = []
		self.allLabels= OrderedDict()
		self.allLabels['Thrust Over Torque']={'x':'Torque Ncm', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'}
		self.allLabels['Thrust Over RPM']={'x':'RPM', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'}
		self.allLabels['Thrust Over Power']={'x':'Watts', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'}
		self.allLabels['Torque Over RPM']={'x':'RPM', 'y':'Torque Ncm', 'yScale':10, 'mode':'scatter'}
		self.allLabels['Efficiency Over RPM']={'x':'RPM', 'y':'Efficiency', 'yScale':10, 'mode':'scatter'}
		self.allLabels['Efficiency Over Thrust']={'x':'Thrust', 'y':'Efficiency', 'yScale':10, 'mode':'scatter'}

		self.clearModeBox()
		self.buildModeBox()

	def onDeleteWindow(self, *args):
		Gtk.main_quit(*args)

	def doMakeChart(self, button):
		patchLoad = None
		allCharts = []
		mode = self.modeBox.get_active_text()
		freeMode = self.freeCheck.get_active()

		for row in self.fileList:
			allPaths = []
			allPaths.append( row['fullPath'][1:] )

		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']
			programName = None
			extraData=None

			if '.patch' in path:
				patchFile = open(path, 'r')
				tempPatch = json.load(patchFile)
				patchFile.close()
				patchLoad = {}
				for key in tempPatch:
					patchLoad[int(key)] = tempPatch[key]

				continue

			if '.prop' in path:
				propFile = open(path, 'r')
				propBase = os.path.basename(path)
				propLoad = json.load(propFile)
				propFile.close()
				print 'loaded prop'
				propData = {}

				for item in propLoad:
					if item['torque'] >= 0:
						for key in item.keys():
							if key not in propData:
								propData[key]=[]
							propData[key].append( item[key])

				if mode == 'Torque Over RPM':
					thisData = { }
					thisData['x']= [round(i) for i in propData['rpm']]
					thisData['y']= [round(i, 4) for i in propData['torque']]
					thisData['thrust_g']= [round(i,2) for i in propData['thrust']]

				elif mode == 'Thrust Over Torque':
					thisData = { }
					thisData['x']= [round(i, 4) for i in propData['torque']]
					thisData['y']= [round(i, 2) for i in propData['thrust']]

				elif mode == 'Thrust Over RPM':
					thisData = { }
					thisData['x']= [round(i) for i in propData['rpm']]
					thisData['y']= [round(i, 2) for i in propData['thrust']]

				elif mode == 'Thrust Over Power':
					thisData = { }

					power = []
					for i in xrange(len(propData['rpm'])):
						rpm = propData['rpm'][i]
						torque = propData['torque'][i]/100
						mechWatts = torque * (rpm * ((2*math.pi)/60) )
						power.append(mechWatts)

					thisData['x']= [round(i, 1) for i in power]
					thisData['y']= [round(i, 2) for i in propData['thrust']]

				elif mode == 'Efficiency Over RPM':
					thisData = { }
					power = []
					eff = []
					for i in xrange(len(propData['rpm'])):
						rpm = propData['rpm'][i]
						thrust = propData['thrust'][i]
						torque = propData['torque'][i]/100
						mechWatts = torque * (rpm * ((2*math.pi)/60) )
						power.append(mechWatts)
						eff.append(thrust/mechWatts)

					thisData['x']= [round(i) for i in propData['rpm'] ]
					thisData['y']= [round(i, 2) for i in eff]

				elif mode == 'Efficiency Over Thrust':
					thisData = { }
					power = []
					eff = []
					for i in xrange(len(propData['rpm'])):
						rpm = propData['rpm'][i]
						thrust = propData['thrust'][i]
						torque = propData['torque'][i]/100
						mechWatts = torque * (rpm * ((2*math.pi)/60) )
						power.append(mechWatts)
						eff.append(thrust/mechWatts)

					thisData['x']= [round(i, 1) for i in propData['thrust'] ]
					thisData['y']= [round(i, 2) for i in eff]


				thisChart = {}
				thisChart['data']=thisData
				thisChart['programName']='prop'
				thisChart['label']=propBase.split('.')[0]
				thisChart['mode']='line'
				thisChart['extraRange']=False
				allCharts.append(thisChart)
				continue


			sample, index = logReader.readBinaryLog(path)
			print 'charting for ', mode


		if freeMode:
			chartBuilder.freelookChart(allCharts, self.allLabels[mode], self.chartTitleEntry.get_text(), mode=mode, patchLoad=patchLoad)
		else:
			chartBuilder.MQTBChart(allCharts, self.allLabels[mode], self.chartTitleEntry.get_text(), mode=mode, patchLoad=patchLoad)

	def doSaveSession(self, button):
		print "save"
		thisSession = []

		for row in self.fileList:
			thisEntry = {}
			thisEntry['path'] = row['fullPath']
			thisEntry['label'] = row['label']
			thisSession.append(thisEntry)

		dumpFile = open('last.bbSession', 'w')
		json.dump(thisSession, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
		dumpFile.close()

	def clearModeBox(self):
		self.modeBox.set_active(0)
		while self.modeBox.get_active_text():
			self.modeBox.remove(0)
			self.modeBox.set_active(0)

	def buildModeBox(self):
		for mode in self.allLabels:
			self.modeBox.append_text(mode)
		self.modeBox.set_active(0)


	def doIntegrateDumpProp(self, button):
		self.clearModeBox()


	def drop_cb(self, wid, context, x, y, time):
		targets = context.list_targets()
		wid.drag_get_data(context, targets[-1], time)
		return True

	def got_data_cb(self, wid, context, x, y, data, info, time):
		paths = data.get_uris()
		for uri in paths:
			path = urlparse.unquote(urlparse.urlparse(uri).path)
			if '.bbSession' in path:
				self.loadSessionFile(path)
			else:
				self.addRow(path)

		context.finish(True, False, time)

	def loadSessionFile(self, path):
		self.doClearAll(None)
		sessionFile = open(path[1:], 'r')
		sessionLoad = json.load(sessionFile)
		sessionFile.close()
		for item in reversed(sessionLoad):
			self.addRow(item['path'], labelText=item['label'] )

	def got_data_ref(self, wid, context, x, y, data, info, time):
		paths = data.get_uris()
		for uri in paths:
			self.refPath = urlparse.unquote(urlparse.urlparse(uri).path[1:])
		self.refEntry.set_text( os.path.basename(self.refPath) )
		context.finish(True, False, time)

	def addRow(self, file, labelText=None):

		thisRow = {}
		thisRow['fullPath']=file
		thisRow['baseName']=os.path.basename(file)
		thisRow['label'] = labelText
		if not thisRow['label']:
			thisRow['label']=thisRow['baseName'].split('.')[0]
		self.fileList = [thisRow]+self.fileList

		self.grid.insert_row(0)
		label = Gtk.Label(thisRow['baseName'])
		entry = Gtk.Entry()
		entry.set_text(thisRow['label'])
		entry.connect('changed', self.labelChange)
		button3 = Gtk.Button(label='x')
		button3.connect('clicked', self.removeClicked)
		self.grid.attach(label, 0, 0, 1,1)
		self.grid.attach_next_to(entry, label, Gtk.PositionType.RIGHT, 1, 1)
		self.grid.attach_next_to(button3, entry, Gtk.PositionType.RIGHT, 1, 1)
		self.grid.show_all()

	def labelChange(self, entry):
		rowIndex = self.grid.child_get_property(entry, 'top-attach')		
		self.fileList[rowIndex]['label']=entry.get_text()

	def removeClicked(self, button):
		rowIndex = self.grid.child_get_property(button, 'top-attach')
		self.grid.remove_row(rowIndex)
		del self.fileList[rowIndex]

	def doClearAll(self, button):
		while len(self.fileList):
			self.grid.remove_row(0)
			del self.fileList[0]

	def write(self, data):
		buffer = self.log.get_buffer()
		iter = buffer.get_end_iter()
		buffer.place_cursor(iter)
		buffer.insert_at_cursor(data)
		iter = buffer.get_end_iter()
		mark = buffer.create_mark('end', iter, False)
		self.log.scroll_to_mark(mark, 0.05, True, 0, 1)
		#self.log.set_text(data)

builder = Gtk.Builder()
builder.add_from_file("./logReader/exploreWin.glade")
label = builder.get_object("label1")
window = builder.get_object("window1")
button = builder.get_object("bttnMakeChart")
clearAll = builder.get_object("bttnClearAll")
dumpChart = builder.get_object("bttnDumpChart")
entry = builder.get_object("refEntry")
window.drag_dest_set(0, [], 0)
button.drag_dest_set(0, [], 0)
entry.drag_dest_set(0, [], 0)
handlerObj = handler(builder)
builder.connect_signals(handlerObj)

window.set_title('Explore - Blade Bench')
window.show_all()

sys.stdout = handlerObj
sys.stderr = handlerObj


Gtk.main()
