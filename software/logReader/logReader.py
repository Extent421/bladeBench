import csv
import copy
import math

from bokeh.plotting import figure, output_file, show, reset_output
from bokeh.models import HoverTool, Range1d, LinearAxis

import numpy.polynomial.polynomial as poly
import numpy

class smoother():
	medTaps = 6
	avgTaps = 6

	def __init__(self, medTaps=6, avgTaps=6):
		self.medAcc = []
		self.avgAcc = []
		self.medTaps = medTaps
		self.avgTaps = avgTaps

	def add(self, value):
			self.medAcc.append(value)
			self.medAcc = self.medAcc[-self.medTaps:]
			med = copy.deepcopy(self.medAcc)
			med.sort()

			self.avgAcc.append(  med[ int(len(med)/2 ) ]  )
			self.avgAcc = self.avgAcc[-self.avgTaps:]
	def get(self):
		sum=0
		for item in self.avgAcc:
			sum += item
		avg=sum/len(self.avgAcc)

		#if len(self.avgAcc) < self.avgTaps:
		#	print self.avgAcc

		return(avg)

MIN_SAMPLE_TIME = 100 #minimum time between sample readings in micros

SAMPLE_TIME	= 1<<0
SAMPLE_MOTORCOMMAND	= 1<<1
SAMPLE_TACH = 1<<2
SAMPLE_VOLT = 1<<3
SAMPLE_AMP = 1<<4
SAMPLE_THRUST = 1<<5
SAMPLE_T1 = 1<<6
SAMPLE_T2 = 1<<7
SAMPLE_T3 = 1<<8
SAMPLE_T4 = 1<<9

TIMEROUNDING = 5

def readLog(file):
	with open(file, 'rb') as csvfile:
		thisLine = ''
		while 'Time,' not in thisLine:
			lastRead = csvfile.tell()
			thisLine = csvfile.readline()
		csvfile.seek(lastRead)

		floatKeys = ['RPM', 'Volt', 'Amp', 'Thrust']
		intKeys = ['Motor Command', 'Time']
		spamreader = csv.DictReader(csvfile, delimiter=',', quotechar='|')
		smooth = smoother()

		allSamples = []
		index = {}
		try:
			for row in spamreader:
				thisSample = {}

				if not index.keys():
					for key in row.keys():
						index[key]=[]

				for key in row.keys():
					thisSample[key]=None

				for key in floatKeys:
					if row[key] != '':
						thisSample[key]=float(row[key])
						index[key].append(len(allSamples))
				for key in intKeys:
					if row[key] != '':
						thisSample[key]=int(row[key])
						index[key].append(len(allSamples))
				allSamples.append(thisSample)
		except:
			pass

	#interpolate
	for key in index:
		seq = index[key]
		for a, b in zip(seq, seq[1:]):
			length = b-a
			if length<2: continue
			start = allSamples[a][key]
			end = allSamples[b][key]
			delta = end-start
			for i in range(1,length):
				allSamples[a+i][key] =start + delta*(float(i)/length)


	return allSamples, index

def readBinaryLog(file):
	import struct

	allKeys = ['RPM', 'Volt', 'Amp', 'Thrust','Motor Command', 'Time', 'T1', 'T2', 'T3', 'T4']
	allSamples = []
	index = {}
	for key in allKeys:
		index[key]=[]

	with open(file, 'rb') as f:
		adcMax = None
		vref = None
		dataStart = None
		for line in iter(f.readline, ''):
			if 'adcMaxValue:' in line:
				adcMax = float(line.split(':')[-1])
			if 'vref:' in line:
				vref = float(line.split(':')[-1])
			if 'thermBValue:' in line:
				thermBValue = float(line.split(':')[-1])
			if line == 'Data Start:\n':
				dataStart = f.tell()
				break
		print 'found start', dataStart, adcMax, vref
		#f.seek(dataStart-1)

		correctionValue = vref/adcMax

		while True:
			thisSample = {}
			for key in allKeys:
				thisSample[key]=None

			data = f.read(2)
			if not len(data): break
			#unpacked = struct.unpack('<H', data)[0]
			#print 'unpacked', format(ord(data[0]), '02x'), format(ord(data[1]), '02x'), unpacked, bin(unpacked)[2:]

			flags = struct.unpack('<H', data)[0]

			if flags & SAMPLE_TIME:
				data = f.read(4)
				if not len(data): break
				unpacked = struct.unpack('<L', data)[0]
				thisSample['Time']=unpacked
				index['Time'].append(len(allSamples))

			if flags & SAMPLE_MOTORCOMMAND:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<h', data)[0]
				thisSample['Motor Command']=unpacked
				index['Motor Command'].append(len(allSamples))

			if flags & SAMPLE_TACH:
				data = f.read(4)
				if not len(data): break
				unpacked = struct.unpack('<L', data)[0]
				if unpacked == 0:
					rpm = -1
				else:
					rpm = (1000000.0/unpacked)*60
				thisSample['RPM']=rpm
				index['RPM'].append(len(allSamples))

			if flags & SAMPLE_VOLT:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]
				adcVolt = unpacked * correctionValue
				calibrationFactor =  13.0153255458302 #6s mode
				calibrationFactor =  5.9652021980316 #3s mode
				sensorVolt = adcVolt * calibrationFactor
				thisSample['Volt']=sensorVolt
				index['Volt'].append(len(allSamples))

			if flags & SAMPLE_AMP:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]
				adcVolt = unpacked * correctionValue
				calibrationFactor = 34.5867331938442
				offset = 0.13
				sensorAmps = adcVolt * calibrationFactor + offset
				thisSample['Amp']=sensorAmps
				index['Amp'].append(len(allSamples))

			if flags & SAMPLE_THRUST:
				data = f.read(4)
				if not len(data): break
				temp = [data[0],data[1],data[2],data[3]]
				#unpacked = struct.unpack_from('<h', ''.join(temp))[0]
				unpacked = struct.unpack_from('<l', data)[0]
				raw = unpacked
				unpacked = unpacked/200.9647
				thisSample['Thrust']=unpacked
				index['Thrust'].append(len(allSamples))

			if flags & SAMPLE_T1:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T1']=cValue
				index['T1'].append(len(allSamples))

			if flags & SAMPLE_T2:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T2']=cValue
				index['T2'].append(len(allSamples))

			if flags & SAMPLE_T3:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T3']=cValue
				index['T3'].append(len(allSamples))

			if flags & SAMPLE_T4:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T4']=cValue
				index['T4'].append(len(allSamples))

			allSamples.append(thisSample)

	#interpolate
	for key in index:
		seq = index[key]
		for a, b in zip(seq, seq[1:]):
			length = b-a
			if length<2: continue
			start = allSamples[a][key]
			end = allSamples[b][key]
			delta = end-start
			for i in range(1,length):
				allSamples[a+i][key] =start + delta*(float(i)/length)


	return allSamples, index

def getInterpolated(indexList, valueList):
	for a, b in zip(indexList, indexList[1:]):
		length = b-a
		if length<2: continue
		start = valueList[a]
		end = valueList[b]
		delta = end-start
		for i in range(1,length):
			valueList[a+i] =start + delta*(float(i)/length)
	return valueList


def getStats(sample, index):
	x = []
	y = []
	startRange = 5.25 * 1000000
	endRange = 6.75 *1000000

	foundStart = 0
	foundEnd = 0

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)

	for sampleIndex in index['Time']:
		time = sample[sampleIndex]['Time']
		if not foundStart and time>startRange:
			foundStart = sampleIndex
		if not foundEnd and time>endRange:
			foundEnd = sampleIndex
		if foundStart and foundEnd:
			break

	v=[]
	a=[]
	t=[]
	w=[]
	e=[]
	r=[]

	for sample in sample[foundStart:foundEnd]:
		v.append(round(sample['Volt'],2))
		a.append(round(sample['Amp'],2))
		watts = sample['Volt']*sample['Amp'] 
		w.append( round(watts, 2) )
		if sample['Thrust']:
			t.append(round(sample['Thrust'],2))
			e.append(round(sample['Thrust']/watts,2))
		if sample['RPM']:
			r.append(int(sample['RPM']))


	print 'stats min max med mean'
	if r: print 'RPM', min(r), max(r), int(numpy.median(numpy.array( r ))), int(numpy.mean(numpy.array( r )))
	if t: print 'thrust', min(t), max(t), numpy.median(numpy.array( t )), round(numpy.mean(numpy.array( t )), 2)
	print 'volts', min(v), max(v), numpy.median(numpy.array( v )), round( numpy.mean(numpy.array( v )), 2 )
	print 'Amps', min(a), max(a), numpy.median(numpy.array( a )),round(numpy.mean(numpy.array( a )), 2)
	print 'watts', min(w), max(w), numpy.median(numpy.array( w )),round(numpy.mean(numpy.array( w )), 2)
	if e: print 'efficiency', min(e), max(e), numpy.median(numpy.array( e )), round(numpy.mean(numpy.array( e )), 2)

	return 

def getWatts(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	#sample, index = readLog('D:\\prop\\1304\\rotorX3020.txt')
	for sampleIndex in index['Thrust']:
		thrust = sample[sampleIndex]['Thrust']
		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']

		smoothV.add( volt )
		smoothA.add( amp )
		smoothT.add ( thrust )
		watts = round(smoothV.get()*smoothA.get()  , 1 )

		y.append(round(smoothT.get(), 2) )
		x.append(watts)

	return x, y

def getEfficiencyOverRPM(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Thrust']:
		thrust = sample[sampleIndex]['Thrust']
		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		rpm = sample[sampleIndex]['RPM']

		smoothV.add( volt )
		smoothA.add( amp )
		smoothT.add ( thrust )
		watts = round(smoothV.get()*smoothA.get()  , 1 )
		if not watts: continue
		y.append(round(smoothT.get(), 2)/watts )
		x.append(rpm)

	return x, y

def getThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=3)
	tSmooth = smoother(avgTaps=1, medTaps=3)
	for sampleIndex in index['Thrust']:
		rpm = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		if rpm > 45000: continue
		if not rpm: continue
		smooth.add( rpm )
		smoothedValue = round(smooth.get(), 3 )
		tSmooth.add( thrust )
		tSmoothedValue = round(tSmooth.get(), 3 )
		x.append(smoothedValue)
		y.append(tSmoothedValue)

	return x, y

def getThrustFit(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother()
	#sample, index = readLog('C:\\Users\\markm\\Documents\\Drones\\PropBenchmarks\\bladeShapes\\rxTri.txt')
	for sampleIndex in index['RPM']:
		rpm = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		if rpm > 45000: continue

		smooth.add( rpm )
		smoothedValue = round(smooth.get(), 3 )
		x.append(smoothedValue)
		y.append(thrust)

	xTrim = x[:int(len(x)*0.5)]
	yTrim = y[:int(len(y)*0.5)]
	#Calculate trendline
	x = numpy.linspace(0, 40000, num=len(xTrim))
	order = 2
	coeffs = poly.polyfit(xTrim,yTrim, order)
	y = poly.polyval(x, coeffs)

	return x, y

def getTestThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=3)
	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		smooth.add( thrust )
		smoothedValue =  round(smooth.get(), 3 )
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		y.append(smoothedValue)
	return x, y

def getTestRpm(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=4, medTaps=1)
	dsmooth = smoother(avgTaps=2, medTaps=6)

	lastGoodTime = 0
	lastValue = 0
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPM']
		if rpm > 60000: 
			print 'False Trigger', lastGoodTime, time, time-lastGoodTime
			continue
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		smooth.add( rpm )
		thisValue = smooth.get()
		if deltaMode:
			dsmooth.add( float(thisValue-lastValue)/(float(time-lastGoodTime)/1000)  )
			y.append( dsmooth.get() )
			lastGoodTime = time
			lastValue = thisValue
		else:
			y.append(thisValue)
	return x, y

def getTestVoltsRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		y.append(volt)
	return x, y

def getTestT1Raw(sample, index):
	x = []
	y = []
	for sampleIndex in index['T1']:
		time = sample[sampleIndex]['Time']
		T1 = sample[sampleIndex]['T1']
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		y.append(T1)
	return x, y

def getCommandRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Motor Command']:
		time = sample[sampleIndex]['Time']
		T1 = sample[sampleIndex]['Motor Command']
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		y.append(T1)
	return x, y

def getTestAmpsRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		y.append(amp)
	return x, y

def getTestVolts(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=1, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		smooth.add( volt )
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append(round(float(time)/1000000, TIMEROUNDING) )
			y.append(smooth.get())
			lastTime = time
	return x, y

def getTestAmps(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=1, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		smooth.add( amp )
				
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append(round(float(time)/1000000, TIMEROUNDING) )
			y.append(smooth.get())
			lastTime = time
	return x, y

def getTestRpmRAW(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	lastGoodTime=0
	lastValue=0
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPM']
		x.append(round(float(time)/1000000, TIMEROUNDING) )

		thisValue = rpm
		if deltaMode:
			y.append( float(thisValue-lastValue)/(float(time-lastGoodTime)/1000) )
			lastGoodTime = time
			lastValue = thisValue
		else:
			y.append(thisValue)

	return x, y

def getLoad(sample, index, unloadedRPM):
	# Motor Load
	x = []
	y = []
	smooth = smoother()
	#sample, index = readLog('C:\\Users\\markm\\Documents\\Drones\\PropBenchmarks\\bladeShapes\\rxTri.txt')
	for sampleIndex in index['RPM']:
		value = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']

		if value > 45000: continue
		x.append(round(float(time)/1000000, TIMEROUNDING) )
		smooth.add( value )
		smootedValue = round(smooth.get(), 3 )
		if unloadedRPM[sampleIndex]==None: continue 
		y.append(100- (smootedValue/unloadedRPM[sampleIndex])*100 )
	return x, y

def getUnloadedBaseline(logPath):
	sample, index = readLog(logPath)

	unloadedRPM = [None]*len(sample)
	unloadedIndex = []
	smooth = smoother(avgTaps=10, medTaps=8)
	for sampleIndex in index['RPM']:
		value = sample[sampleIndex]['RPM']

		if value > 60000: continue
		smooth.add( value )
		unloadedRPM[sampleIndex] = round(smooth.get(), 3 )
		unloadedIndex.append(sampleIndex)

	getInterpolated(unloadedIndex, unloadedRPM)
	return unloadedRPM

def buildFigure(dataList, labelList, deltaMode, chartTitle=None):
	colors = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'blue', 'green','red']
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']
	if deltaMode:
		yScale = labelList['yScaleDelta']

	hover = HoverTool(
		tooltips = [
			#("index", "$index"),
			(xLabel, "@x{1.11}"),
			(yLabel, "@y{int}"),
		],
		#mode='vline',

	)

	p = figure(
		width=1520, plot_height=880,
		tools=[hover,'pan','box_zoom','wheel_zoom', 'reset','crosshair'],#"resize,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
		active_scroll='wheel_zoom',
		y_range=[0, yScale],
		x_axis_label=xLabel,# y_axis_label=yLabel,
		webgl=True,
		title=chartTitle
	)
	

	defaultRange = 'default_range'
	p.extra_y_ranges.update( {defaultRange: Range1d(start=0, end=yScale)} )
	p.add_layout(LinearAxis(y_range_name=defaultRange,  axis_label=yLabel), 'left')

	for item in dataList[::-1]:
		print 'creating plot for', item['label'], item['mode']
		thisRange = defaultRange
		if item['extraRange']:
			rangeName = item['label'] + '_range'
			print "made range", rangeName, item['extraRange']
			p.extra_y_ranges.update( {rangeName: Range1d(start=0, end=item['extraRange'])} )
			p.add_layout(LinearAxis(y_range_name=rangeName, axis_label=item['extraLabel']), 'left')
			thisRange = rangeName

		if item['mode']=='line':
			p.line(item['x'], item['y'], legend=item['label'], color=colors.pop(), line_width=3, y_range_name=thisRange)

		else:
			p.scatter(item['x'], item['y'], legend=item['label'], color=colors.pop(), size=5, y_range_name=thisRange)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"

	show(p)
	reset_output()

def run():
	sample, index = readLog('D:\\prop\\1304\\rotorX3020.txt')
	x,y = getThrust(sample, index)

	sample, index = readLog('D:\\prop\\1304\\rotorX3025.txt')
	x2,y2 = getThrust(sample, index)

	sample, index = readLog('D:\\prop\\1304\\RotorX2535x4.txt')
	x3,y3 = getThrust(sample, index)

	sample, index = readLog('D:\\prop\\1304\\HQ3030.txt')
	x4,y4 = getThrust(sample, index)



	print 'done'


	xLabel = 'Watts'
	yLabel = 'Thrust'

	hover = HoverTool(
	        tooltips = [
		    ("index", "$index"),
		    (xLabel, "$x"),
		    (yLabel, "@y{int}"),
			]
	    )



	p = figure(
		width=1520, plot_height=880,
	   tools=[hover,'pan','box_zoom','wheel_zoom', 'reset'],#"resize,crosshair,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
	   active_scroll='wheel_zoom',
	   y_range=[0, 260], title="test",
	   x_axis_label=xLabel, y_axis_label=yLabel,
	   webgl=True
	)


	# add some renderers
	line = p.scatter(x, y, legend="3020", color="red", size=5)
	line2 = p.scatter(x2, y2, legend="3025", color="green", size=5)
	line3 = p.scatter(x3, y3, legend="2535", color="blue", size=5)
	line4 = p.scatter(x4, y4, legend="HQ3030", color="orange", size=5)

	#print x2
	'''
	p.add_tools(HoverTool(renderers=[line2],
	        tooltips = [
		    ("index", "A"),
		    ("time", "$x"),
		    ("RPM", "@y{int}"),
			]
	    )
	)
	'''
	#p.add_tools(HoverTool(renderers=[line2],
	#        tooltips = [
	#	    ("index", "B"),
	#	    ("time", "$x"),
	#	    ("RPM", "@y{int}"),
	#		]
	#    )
	#)
	# show the results
	show(p)




