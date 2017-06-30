import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import urlparse
import os
import sys
import time

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

	def onDeleteWindow(self, *args):
		Gtk.main_quit(*args)

	def testPressed(self, button):
		allCharts = []
		allLabels= {'thrust':{'x':'RPM', 'y':'Thrust', 'yScale':250, 'mode':'scatter'},
					'thrustFit':{'x':'RPM', 'y':'Thrust', 'yScale':250, 'mode':'line'},
					'testThrust':{'x':'Time', 'y':'Thrust', 'yScale':250, 'mode':'scatter'},
					'testRpm':{'x':'Time', 'y':'RPM', 'yScale':40000,  'yScaleDelta':600, 'mode':'scatter'},
					'testRpmRAW':{'x':'Time', 'y':'RPM', 'yScale':40000,  'yScaleDelta':600, 'mode':'scatter'},
					'load':{'x':'Time', 'y':'Load', 'yScale':100, 'mode':'scatter'},
					'watts':{'x':'Watts', 'y':'Thrust', 'yScale':250, 'mode':'scatter'},
					'EfficiencyOverRPM':{'x':'RPM', 'y':'G/W', 'yScale':10, 'mode':'scatter'},
					'V':{'x':'Time', 'y':'Volts', 'yScale':20, 'mode':'scatter'},
					'A':{'x':'Time', 'y':'Amps', 'yScale':30, 'mode':'scatter'},
					'overview':{'x':'Time', 'y':'Amps', 'yScale':10, 'mode':'scatter'},
					'VRaw':{'x':'Time', 'y':'Volts', 'yScale':20, 'mode':'scatter'},
					'ARaw':{'x':'Time', 'y':'Amps', 'yScale':30, 'mode':'scatter'},
					'T1Raw':{'x':'Time', 'y':'degrees C', 'yScale':30, 'mode':'scatter'},
					'commandRaw':{'x':'Time', 'y':'Motor Command', 'yScale':2000, 'mode':'line'},
					}
		mode = self.modeBox.get_active_id()

		for row in self.fileList:
			path = row['fullPath'][1:]
			label = row['label']
			sample, index = logReader.readBinaryLog(path)
			deltaMode = self.deltaCheck.get_active()
			print 'charting for ', mode
			if mode == 'stats':
				resultDict = logReader.getStats(sample,index)
				return
			elif mode == 'thrust':
				x,y = logReader.getThrust(sample, index)
			elif mode == 'thrustFit':
				x,y = logReader.getThrustFit(sample, index)
			elif mode == 'testThrust':
				x,y = logReader.getTestThrust(sample, index)
			elif mode == 'testRpm':
				x,y = logReader.getTestRpm(sample, index, deltaMode=deltaMode)
			elif mode == 'testRpmRAW':
				x,y = logReader.getTestRpmRAW(sample, index, deltaMode=deltaMode)
			elif mode == 'load':
				baseline = logReader.getUnloadedBaseline(self.refPath)
				x,y = logReader.getLoad(sample, index, baseline)
			elif mode == 'watts':
				x,y = logReader.getWatts(sample, index)
			elif mode == 'EfficiencyOverRPM':
				x,y = logReader.getEfficiencyOverRPM(sample, index)
			elif mode == 'V':
				x,y = logReader.getTestVolts(sample, index)
			elif mode == 'A':
				x,y = logReader.getTestAmps(sample, index)
			elif mode == 'VRaw':
				x,y = logReader.getTestVoltsRaw(sample, index)
			elif mode == 'ARaw':
				x,y = logReader.getTestAmpsRaw(sample, index)
			elif mode == 'T1Raw':
				x,y = logReader.getTestT1Raw(sample, index)
			elif mode == 'commandRaw':
				x,y = logReader.getCommandRaw(sample, index)
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
			thisChart['x']=x
			thisChart['y']=y
			thisChart['label']=label
			thisChart['mode']=allLabels[mode]['mode']
			print 'set Mode to', thisChart['mode']
			thisChart['extraRange']=False
			allCharts.append(thisChart)
		logReader.buildFigure(allCharts, allLabels[mode], deltaMode, self.chartTitleEntry.get_text())



	def drop_cb(self, wid, context, x, y, time):
		targets = context.list_targets()
		print 'main', targets
		wid.drag_get_data(context, targets[-1], time)
		return True

	def got_data_cb(self, wid, context, x, y, data, info, time):
		print data
		paths = data.get_uris()
		for uri in paths:
			path = urlparse.unquote(urlparse.urlparse(uri).path)
			self.addRow(path)

		context.finish(True, False, time)


	def got_data_ref(self, wid, context, x, y, data, info, time):
		paths = data.get_uris()
		for uri in paths:
			self.refPath = urlparse.unquote(urlparse.urlparse(uri).path[1:])
		self.refEntry.set_text( os.path.basename(self.refPath) )
		context.finish(True, False, time)

	def addRow(self, file):

		thisRow = {}
		thisRow['fullPath']=file
		thisRow['baseName']=os.path.basename(file)
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
button = builder.get_object("button1")
entry = builder.get_object("refEntry")
window.drag_dest_set(0, [], 0)
button.drag_dest_set(0, [], 0)
entry.drag_dest_set(0, [], 0)
handlerObj = handler(builder)
builder.connect_signals(handlerObj)

window.show_all()

sys.stdout = handlerObj
sys.stderr = handlerObj


Gtk.main()
