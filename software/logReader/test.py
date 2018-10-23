import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import urlparse
import os
import sys
import time
import json

import shutil
import numpy

sys.path.insert(0, os.path.abspath(".."))
from . import logReader

class handler:
	def __init__(self, builder, *args):
		self.builder = builder
		self.label = builder.get_object("label1")
		self.grid = builder.get_object("grid1")
		self.log = builder.get_object("textview1")
		self.logScroll = builder.get_object("logScroll")
		self.modeBox = builder.get_object("modeBox")
		self.refEntry = builder.get_object("refEntry")
		self.deltaCheck = builder.get_object("deltaCheck")
		self.chartTitleEntry = builder.get_object("chartTitleEntry")
		self.refPath = ''
		self.fileList = []
		self.logCache={}

	def onDeleteWindow(self, *args):
		Gtk.main_quit(*args)

	def doMakeChart(self, button):
		patchLoad = None
		torqueLoad = None
		propLoad = None
		propCharts = []
		allCharts = []
		torqueDump = []
		allLabels= {'Thrust Over RPM':{'x':'RPM', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'},
					'Thrust Fitline':{'x':'RPM', 'y':'Thrust g', 'yScale':250, 'mode':'line'},
					'Test Thrust':{'x':'Time', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'},
					'Test Thrust Residual':{'x':'Time', 'y':'Thrust g', 'yScale':250, 'mode':'scatter'},
					'Test Torque':{'x':'Time', 'y':'Torque Ncm', 'yScale':10, 'mode':'scatter'},
					'Test Torque Residual':{'x':'Time', 'y':'Torque Ncm', 'yScale':5, 'mode':'scatter'},
					'Test Watts':{'x':'Time', 'y':'Watts', 'yScale':250, 'mode':'scatter'},
					'Thrust Over Throttle':{'x':'Throttle', 'y':'Thrust', 'yScale':250, 'mode':'scatter'},
					'RPM Over Throttle':{'x':'Throttle', 'y':'RPM', 'yScale':40000, 'mode':'scatter'},
					'Test RPM':{'x':'Time', 'y':'RPM', 'yScale':40000,  'yScaleDelta':600, 'mode':'scatter'},
					'testRpmRAW':{'x':'Time', 'y':'RPM', 'yScale':40000,  'yScaleDelta':600, 'mode':'scatter'},
					'Load':{'x':'Time', 'y':'Load', 'yScale':100, 'mode':'scatter'},
					'Watts':{'x':'Watts', 'y':'Thrust', 'yScale':250, 'mode':'scatter'},
					'MechPower':{'x':'Watts', 'y':'Time', 'yScale':250, 'mode':'scatter'},
					'Torque Over RPM':{'x':'RPM', 'y':'Torque Ncm', 'yScale':10, 'mode':'scatter'},
					'Inertia':{'x':'Time', 'y':'Inertia g cm^2', 'yScale':40, 'mode':'scatter'},
					'InertiaSingle':{'x':'Time', 'y':'Inertia g cm^2', 'yScale':40, 'mode':'scatter'},
					'MechEff':{'x':'Time', 'y':'Efficiency', 'yScale':1, 'mode':'scatter'},
					'Efficiency Over RPM':{'x':'RPM', 'y':'G/W', 'yScale':10, 'mode':'scatter'},
					'Efficiency Over Throttle':{'x':'Throttle', 'y':'G/W', 'yScale':10, 'mode':'scatter'},
					'Test V':{'x':'Time', 'y':'Volts', 'yScale':20, 'mode':'scatter'},
					'Test A':{'x':'Time', 'y':'Amps', 'yScale':30, 'mode':'scatter'},
					'overview':{'x':'Time', 'y':'Amps', 'yScale':10, 'mode':'scatter'},
					'VRaw':{'x':'Time', 'y':'Volts', 'yScale':20, 'mode':'scatter'},
					'ARaw':{'x':'Time', 'y':'Amps', 'yScale':30, 'mode':'scatter'},
					'T1Raw':{'x':'Time', 'y':'degrees C', 'yScale':30, 'yScaleDelta':20, 'mode':'scatter'},
					'T2Raw':{'x':'Time', 'y':'degrees C', 'yScale':30, 'yScaleDelta':20, 'mode':'scatter'},
					'T4Raw':{'x':'Time', 'y':'degrees C', 'yScale':30, 'yScaleDelta':20, 'mode':'scatter'},
					'Thrust Over T1':{'x':'degrees C', 'y':'Thrust', 'yScale':300, 'mode':'scatter'},
					'Thrust Over V':{'x':'Volts', 'y':'Thrust', 'yScale':300, 'mode':'scatter'},
					'commandRaw':{'x':'Time', 'y':'Motor Command', 'yScale':2000, 'mode':'line'},
					'auxRaw':{'x':'Time', 'y':'Aux Command', 'yScale':2000, 'mode':'line'},
					'MQTBDump':{'x':'Time', 'y':'Aux Command', 'yScale':2000, 'mode':'line'},

					}
		mode = self.modeBox.get_active_id()

		#preload 
		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']

			if '.patch' in path:
				patchFile = open(path, 'r')
				tempPatch = json.load(patchFile)
				patchFile.close()
				patchLoad = {}
				for key in tempPatch:
					patchLoad[int(key)] = tempPatch[key]
				print 'loaded patch', path
				continue

			if '.torque' in path:
				torqueFile = open(path, 'r')
				tempTorque = json.load(torqueFile)
				torqueFile.close()
				torqueLoad = {}
				for key in tempTorque:
					torqueLoad[int(key)] = tempTorque[key]
				print 'loaded torque', path

				continue

			if '.prop' in path:
				if mode == 'Inertia':
					propFile = open(path, 'r')
					propBase = os.path.basename(path)
					propLoad = json.load(propFile)
					propFile.close()
				continue



		for row in self.fileList:
			allPaths = []
			allPaths.append( row['fullPath'][1:] )

			for key in self.logCache.keys():
				if key not in allPaths:
					print 'expiring', key
					del self.logCache[key]


		if mode == 'Torque Over RPM':
			idleValues=[]
			for row in self.fileList:
				path = row['fullPath'][1:]
				if '.patch' in path: continue
				if '.prop' in path: continue

				sample, index = logReader.readBinaryLog(path, shortLoad = 5.1)
				medVal = logReader.getIdleThrust(sample, index)
				idleValues.append(medVal)

			idleOffset = 0
			if idleValues:
				idleOffset = -(sum(idleValues))/len(idleValues)
			print "found idle offset:", idleOffset


		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']
			programName = None
			extraData=None
			deltaMode = self.deltaCheck.get_active()

			if '.patch' in path:
				continue

			if '.torque' in path:
				continue

			if '.prop' in path:
				propFile = open(path, 'r')
				propBase = os.path.basename(path)
				propLoad = json.load(propFile)
				propFile.close()
				propCharts.append(propLoad)

				if mode == 'Inertia': continue


				x = []
				y = []
				z = []

				print 'loaded prop'
				for item in propLoad:
					if item['torque'] >= 0:
						x.append( item['rpm'])
						y.append( item['torque'])
						z.append( item['thrust'])

				extraData = {}
				extraData['z'] = z

				thisChart = {}
				thisChart['x']=x
				thisChart['y']=y

				thisChart['data'] = {}
				thisChart['data']['x']=x
				thisChart['data']['y']=y
				thisChart['data']['thrust_g']=z


				thisChart['extraData']=extraData
				thisChart['programName']='prop'
				thisChart['label']=propBase.split('.')[0]
				thisChart['mode']='line'
				thisChart['extraRange']=False
				allCharts.append(thisChart)
				continue

			'''if path not in self.logCache.keys():
				print 'caching', path
				sample, index = logReader.readBinaryLog(path)
				self.logCache[path]= [ sample, index ]
'''


			if mode == 'rename':
				thisLog = logReader.bladeBenchLog(path)
				fullProgramName = thisLog.getProgramName()
				programName = fullProgramName.split('.')[0]
				dir = os.path.dirname(path)
				targetPath = os.path.join(dir, programName+'.txt')
				increment = 0
				while os.path.isfile(targetPath):
					increment = increment + 1
					targetPath = os.path.join(dir, programName+'('+ str(increment) +').txt')
					if increment >100: break

				print 'copying from', path, 'to', targetPath
				shutil.copyfile(path, targetPath)
				continue


			sample, index = logReader.readBinaryLog(path)

			#sample = self.logCache[path][0]
			#index = self.logCache[path][1]
			print 'charting for ', mode



			if mode == 'stats':
				resultDict = logReader.getStats(sample,index)
				return
			if mode == 'calibrationStats':
				resultDict = logReader.getCalibrationStats(sample,index)
				return
			elif mode == 'Thrust Over RPM':
				x,y = logReader.getThrust(sample, index)
			elif mode == 'Thrust Fitline':
				x,y = logReader.getThrustFit(sample, index)
			elif mode == 'Test Thrust':
				x,y = logReader.getTestThrust(sample, index)
			elif mode == 'Test Thrust Residual':
				x,y = logReader.getTestThrustResidual(sample, index)
			elif mode == 'Test Torque':
				x,y = logReader.getTestThrust(sample, index)
				y = [v*100 for v in y]  #Nm to Ncm
			elif mode == 'Test Torque Residual':
				x,y = logReader.getTestThrustResidual(sample, index)
				y = [v*100 for v in y]  #Nm to Ncm
			elif mode == 'Thrust Over Throttle':
				x,y = logReader.getThrottleThrust(sample, index)
			elif mode == 'RPM Over Throttle':
				x,y = logReader.getRpmOverThrottle(sample, index)
			elif mode == 'Test RPM':
				x,y = logReader.getTestRpm(sample, index, deltaMode=deltaMode)
			elif mode == 'Test RPM Raw':
				x,y = logReader.getTestRpm(sample, index, deltaMode=deltaMode)
			elif mode == 'Test Watts':
				x,y = logReader.getTestWatts(sample, index)
			elif mode == 'testRpmRAW':
				x,y = logReader.getTestRpmRAW(sample, index, deltaMode=deltaMode)
			elif mode == 'Load':
				baseline = logReader.getUnloadedBaseline(self.refPath)
				x,y = logReader.getLoad(sample, index, baseline)
			elif mode == 'Watts':
				x,y = logReader.getWatts(sample, index)
			elif mode == 'MechPower':
				x,y = logReader.getMechanicalPower(sample, index)
			elif mode == 'MechEff':
				x,y = logReader.getMechanicalEff(sample, index)
			elif mode == 'Torque Over RPM':
				x,y,extraData,programName = logReader.getTorqueOverRPM(sample, index, idleOffset)
				y = [v*100 for v in y]  #Nm to Ncm
			elif mode == 'Inertia':
				x,y = logReader.getInertia(sample, index, torqueLoad, propLoad)
				print 'Inertia Stats, min, max, med, mean'
				print round(min(y),4), round(max(y),4),round( numpy.median(y),4), round(numpy.mean(y),4)
			elif mode == 'InertiaSingle':
				x,y = logReader.getInertiaSingle(sample, index)
				print 'Inertia Stats, min, max, med, mean'
				print round(min(y),4), round(max(y),4),round( numpy.median(y),4), round(numpy.mean(y),4)

			elif mode == 'Efficiency Over RPM':
				x,y = logReader.getEfficiencyOverRPM(sample, index)
			elif mode == 'Efficiency Over Throttle':
				x,y = logReader.getEfficiencyOverThrottle(sample, index)
			elif mode == 'Test V':
				x,y = logReader.getTestVolts(sample, index)
			elif mode == 'Test A':
				x,y = logReader.getTestAmps(sample, index)
			elif mode == 'VRaw':
				x,y = logReader.getTestVoltsRaw(sample, index)
			elif mode == 'ARaw':
				x,y = logReader.getTestAmpsRaw(sample, index)
			elif mode == 'T1Raw':
				x,y = logReader.getTestTRaw(sample, index, deltaMode=deltaMode, sensor='T1')
			elif mode == 'T2Raw':
				x,y = logReader.getTestTRaw(sample, index, deltaMode=deltaMode, sensor='T2')
			elif mode == 'T4Raw':
				x,y = logReader.getTestTRaw(sample, index, deltaMode=deltaMode, sensor='T4')
			elif mode == 'Thrust Over T1':
				x,y = logReader.getThrustOverT1(sample, index)
			elif mode == 'Thrust Over V':
				x,y = logReader.getThrustOverV(sample, index)
			elif mode == 'commandRaw':
				x,y = logReader.getCommandRaw(sample, index, trace='Motor')
			elif mode == 'auxRaw':
				x,y = logReader.getCommandRaw(sample, index, trace='Aux')
			elif mode == 'MQTBDump':
				x,y = logReader.MQTBDump(sample, index)
				return
			elif mode == 'overview':
				x,y = logReader.getCommandRaw(sample, index)
				thisChart = {}
				thisChart['x']=x
				thisChart['y']=y
				thisChart['label']=label + '_command'
				thisChart['mode']=allLabels['commandRaw']['mode']
				thisChart['extraRange']=allLabels['commandRaw']['yScale']
				thisChart['extraLabel']=allLabels['commandRaw']['y']
				allCharts.append(thisChart)

				x,y = logReader.getTestRpm(sample, index)
				thisChart = {}
				thisChart['x']=x
				thisChart['y']=y
				thisChart['label']=label + '_RPM'
				thisChart['mode']=allLabels['testRpmRAW']['mode']
				thisChart['extraRange']=allLabels['testRpmRAW']['yScale']
				thisChart['extraLabel']=allLabels['testRpmRAW']['y']
				allCharts.append(thisChart)

				x,y = logReader.getTestAmps(sample, index)

			thisChart = {}
			thisChart['data'] = {}
			thisChart['x']=x
			thisChart['y']=y
			thisChart['data']['x']=x
			thisChart['data']['y']=y
			thisChart['extraData']=extraData
			thisChart['programName']=programName
			thisChart['label']=label
			thisChart['mode']=allLabels[mode]['mode']
			print 'set Mode to', thisChart['mode']
			thisChart['extraRange']=False
			allCharts.append(thisChart)
			if mode == 'Torque Over RPM':
				torqueDump.append(thisChart)

		if mode == 'rename': return

		if mode == 'Torque Over RPM':
			torqueDict = {}
			staticLoad = []
			for chart in torqueDump:
				try:
					throttle = int(chart['programName'].split('_')[0])
				except:
					throttle = 0
				torqueDict[throttle]=[]
				staticLoad.append( {
					'rpm':int( round( chart['x'][0] )),
					'thrust':0,
					'command':(throttle/100.0)*2000,
					'torque':round(chart['y'][0], 4 )
				})

				for index in range(0,len(chart['x'])):
					thisPoint = {}
					thisPoint['rpm']=int( round( chart['x'][index] ) )
					thisPoint['torque']=round( chart['y'][index], 4 )
					thisPoint['inWatts']=round( chart['extraData']['inWatts'][index], 1 )
					thisPoint['inVolts']=round( chart['extraData']['inVolts'][index], 1 )
					thisPoint['eff']=round( chart['extraData']['z'][index], 2 )
					torqueDict[throttle].append(thisPoint)

			staticLoad.sort(key=lambda x: x['command']  )


			dumpFile = open('last.torque', 'w')
			json.dump(torqueDict, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
			dumpFile.close()

			dumpFile = open('minLoad.prop', 'w')
			json.dump(staticLoad, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
			dumpFile.close()



		logReader.buildFigure(allCharts, allLabels[mode], deltaMode, self.chartTitleEntry.get_text(), mode=mode, patchLoad=patchLoad)

	def doDumpProp(self, button):
		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']

			if '.patch' in path:
				continue

			if '.prop' in path:
				continue

			sample, index = logReader.readBinaryLog(path)

			dump = logReader.createPropDump(sample, index)

	def doIntegrateDumpProp(self, button):


		idleValues=[]
		for row in self.fileList:
			path = row['fullPath'][1:]
			if '.patch' in path: continue
			if '.prop' in path: continue

			sample, index = logReader.readBinaryLog(path, shortLoad = 5.1)
			medVal = logReader.getIdleThrust(sample, index)
			idleValues.append(medVal)

		idleOffset = 0
		if idleValues:
			idleOffset = -(sum(idleValues))/len(idleValues)
		print "found idle offset:", idleOffset


		thisProp = None
		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']
			if '.prop' in path:
				propFile = open(path, 'r')
				thisProp = json.load(propFile)
				propFile.close()

		if not thisProp:
			print 'no prop dump found to integrate'
			return

		for row in self.fileList:
			path = row['fullPath'][1:]
			if '.patch' in path:
				continue
			if '.prop' in path:
				continue

			sample, index = logReader.readBinaryLog(path)

			thisProp = logReader.integratePropDump(sample, index, thisProp, idleOffset)



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
builder.add_from_file("./logReader/testWin.glade")
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

window.set_title('Parse - Blade Bench')

window.show_all()

sys.stdout = handlerObj
sys.stderr = handlerObj


Gtk.main()
