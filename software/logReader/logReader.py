import csv
import copy
import math
import json

from bokeh.plotting import figure, output_file, show, reset_output, ColumnDataSource
from bokeh.models import HoverTool, Range1d, LinearAxis, LinearColorMapper, ColorBar, BasicTicker, PrintfTickFormatter, CustomJS, TapTool, Slider, widgets
from bokeh.layouts import row, widgetbox
from bokeh import events

import numpy.polynomial.polynomial as poly
import numpy


from . import parseV3
from . import parseV4
from . import util

dynoStartTime = 9.25
dynoEndTime = 12.8
dynoPreLoad = 0

MIN_SAMPLE_TIME = 100 #minimum time between sample readings in micros



class smoother():
	medTaps = 6
	avgTaps = 6

	def __init__(self, medTaps=6, avgTaps=6, preAvgTaps=1):
		self.medAcc = []
		self.avgAcc = []
		self.preAvgAcc = []
		self.medTaps = medTaps
		self.avgTaps = avgTaps
		self.preAvgTaps = preAvgTaps

	def add(self, value):
			self.preAvgAcc.append(value)
			self.preAvgAcc = self.preAvgAcc[-self.preAvgTaps:]
			preAvgVal = numpy.mean(self.preAvgAcc)

			self.medAcc.append(preAvgVal)
			self.medAcc = self.medAcc[-self.medTaps:]

			medVal = numpy.median(self.medAcc)
			self.avgAcc.append( medVal  )
			self.avgAcc = self.avgAcc[-self.avgTaps:]

	def get(self):
		#if len(self.avgAcc) < self.avgTaps:
		#	print self.avgAcc

		return(numpy.mean(self.avgAcc))


class KalmanFilter(object):

    def __init__(self, process_variance, estimated_measurement_variance):
        self.process_variance = process_variance
        self.estimated_measurement_variance = estimated_measurement_variance
        self.posteri_estimate = 0.0
        self.posteri_error_estimate = 1.0

    def add(self, measurement):
        priori_estimate = self.posteri_estimate
        priori_error_estimate = self.posteri_error_estimate + self.process_variance

        blending_factor = priori_error_estimate / (priori_error_estimate + self.estimated_measurement_variance)
        self.posteri_estimate = priori_estimate + blending_factor * (measurement - priori_estimate)
        self.posteri_error_estimate = (1 - blending_factor) * priori_error_estimate

    def get(self):
        return self.posteri_estimate


def readLog(file):
	print 'parsing log', file
	with open(file, 'rb') as csvfile:
		thisLine = ''
		while 'Time,' not in thisLine:
			lastRead = csvfile.tell()
			thisLine = csvfile.readline()
		csvfile.seek(lastRead)

		floatKeys = ['RPM', 'Volt', 'Amp', 'Thrust']
		intKeys = ['Motor Command', 'Time']
		csv = csv.DictReader(csvfile, delimiter=',', quotechar='|')

		allSamples = []
		index = {}
		try:
			for row in csv:
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


def readBinaryLog(file, shortLoad=None):

	fileVersion = None
	allSamples = None
	index = None
	with open(file, 'rb') as f:
		for line in iter(f.readline, ''):
			if 'log version:' in line:
				fileVersion = int(line.split(':')[-1])

	if fileVersion == 3:
		allSamples, index = parseV3.readBinaryLog(file, shortLoad)
	elif fileVersion == 4:
		allSamples, index = parseV4.readBinaryLog(file, shortLoad)
	else:
		print 'unknown file version'


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


def getStats(allSample, index):
	x = []
	y = []
	startRange = 5.25 * 1000000
	endRange = 6.75 *1000000

	foundStart = 0
	foundEnd = 0

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=1, medTaps=3)

	for sampleIndex in index['Time']:
		time = allSample[sampleIndex]['Time']
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

	for sample in allSample[foundStart:foundEnd]:
		v.append(round(sample['Volt'],2))
		a.append(round(sample['Amp'],2))
		watts = sample['Volt']*sample['Amp'] 
		w.append( round(watts, 2) )
		if sample['Thrust']:
			smoothT.add ( sample['Thrust'] )

			t.append(round(smoothT.get(),2))
			e.append(round(smoothT.get()/watts,2))
		if sample['RPM']:
			r.append(int(sample['RPM']))


	v = getMiddleResults(v)
	a = getMiddleResults(a)
	t = getMiddleResults(t)
	w = getMiddleResults(w)
	e = getMiddleResults(e)
	r = getMiddleResults(r)

	print 'stats min max med mean'
	if r: print 'RPM', min(r), max(r), int(numpy.median(numpy.array( r ))), int(numpy.mean(numpy.array( r )))
	if t: print 'thrust', min(t), max(t), numpy.median(numpy.array( t )), round(numpy.mean(numpy.array( t )), 2)
	print 'volts', min(v), max(v), numpy.median(numpy.array( v )), round( numpy.mean(numpy.array( v )), 2 )
	print 'Amps', min(a), max(a), numpy.median(numpy.array( a )),round(numpy.mean(numpy.array( a )), 2)
	print 'watts', min(w), max(w), numpy.median(numpy.array( w )),round(numpy.mean(numpy.array( w )), 2)
	if e: print 'efficiency', min(e), max(e), numpy.median(numpy.array( e )), round(numpy.mean(numpy.array( e )), 2)

	return 

def getCalibrationStats(allSample, index):

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=1, medTaps=3)


	v=[]
	a=[]
	t=[]

	for sample in allSample:

		v.append( sample['VoltADC'] )
		a.append( sample['AmpADC'] )

		if 'ThrustADC' in sample.keys():
			t.append( sample['ThrustADC'] )


	print 'stats samples min max med mean'
	print 'volts', len(v), min(v), max(v), numpy.median(numpy.array( v )), round( numpy.mean(numpy.array( v )), 8 )
	print 'Amps', len(a), min(a), max(a), numpy.median(numpy.array( a )),round(numpy.mean(numpy.array( a )), 8)
	print 'Thrust', len(t), min(t), max(t), numpy.median(numpy.array( t )),round(numpy.mean(numpy.array( t )), 8)

	return 

def getMiddleResults(samples, factor=0.1):
	return sorted(samples)[int(len(samples)*factor):-int(len(samples)*factor)] #remove the top and bottom 10% of results

def getWatts(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Volt']:

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		watts = round(smoothV.get()*smoothA.get()  , 1 )

		y.append(round(smoothT.get(), 2) )
		x.append(watts)

	return x, y

def getEfficiencyOverRPM(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=5, medTaps=29)
	for sampleIndex in index['Volt']:

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		rpm = sample[sampleIndex]['RPM']

		watts = round(smoothV.get()*smoothA.get()  , 1 )
		if not watts: continue
		y.append(round(smoothT.get(), 2)/watts )
		x.append(rpm)

	return x, y

def getMechanicalPower(sample, index):
	x = []
	y = []

	smoothT = smoother(avgTaps=5, medTaps=29)
	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['ThrustF']
		rpm = sample[sampleIndex]['RPM']

		if not rpm: continue

		mechWatts = thrust * (rpm * ((2*math.pi)/60) )
		y.append( round(mechWatts, 2) )
		x.append( util.getFloatTime(time) )

	return x, y

def getTestWatts(sample, index):
	x = []
	y = []

	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']

		volt = sample[sampleIndex]['VoltF']
		amp = sample[sampleIndex]['AmpF']
		
		watts = volt*amp
		if not watts: continue
		y.append(round(watts, 2) )
		x.append( util.getFloatTime(time) )

	return x, y

def getMechanicalEff(sample, index):
	x = []
	y = []

	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		#if roundedTime<11: continue
		#if roundedTime>15: continue

		volt = sample[sampleIndex]['VoltF']
		amp = sample[sampleIndex]['AmpF']

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['ThrustF']
		rpm = sample[sampleIndex]['RPM']

		if not rpm: continue
		
		mechWatts = thrust * (rpm * ((2*math.pi)/60) )
		watts = volt*amp
		if not watts: continue
		y.append(round(mechWatts/watts, 2) )
		x.append(roundedTime)

	return x, y

def getTorqueOverRPM(sample, index, idleOffset=0):
	x = []
	y = []
	z = []
	command = []
	inWatts = []

	thisProgramName = sample[0]['programName']

	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if roundedTime<dynoStartTime-dynoPreLoad: continue
		if roundedTime>dynoEndTime: continue

		volt = sample[sampleIndex]['VoltF']
		amp = sample[sampleIndex]['AmpF']

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['ThrustF']+idleOffset
		if roundedTime<dynoStartTime: continue

		rpm = sample[sampleIndex]['RPMF']

		if not rpm: continue
		
		mechWatts = thrust * (rpm * ((2*math.pi)/60) )
		watts = volt*amp
		if not watts: continue

		y.append(round(thrust, 4) )
		x.append(rpm)
		z.append(round(mechWatts/watts, 2) )
		inWatts.append(round(watts, 1) )
		command.append(sample[sampleIndex]['Motor Command'] )

	accX = []
	accZ = []
	accInWatts = []


	mergedX = []
	mergedY = []
	mergedZ = []
	mergedCommand = []
	mergedInWatts = []
	lastValue = y[0]

	for index in range(0,len(x)):
		if y[index] != lastValue:
			mergedY.append(lastValue)
			mergedCommand.append(command[index])
			mergedX.append(numpy.mean(accX))
			mergedZ.append(numpy.mean(accZ))
			mergedInWatts.append(numpy.mean(accInWatts))
			accX = []
			accZ = []
			accInWatts = []

			lastValue = y[index]

		accX.append(x[index])
		accZ.append(z[index])
		accInWatts.append(inWatts[index])


		extraData = {}
		extraData['z'] = mergedZ
		extraData['inWatts'] = mergedInWatts
		extraData['command'] = mergedCommand

	return mergedX, mergedY, extraData, thisProgramName

def getEfficiencyOverThrottle(sample, index):
	x = []
	y = []

	for sampleIndex in index['Thrust']:

		volt = sample[sampleIndex]['VoltF']
		amp = sample[sampleIndex]['AmpF']
		thrust = sample[sampleIndex]['ThrustF']

		throttle = sample[sampleIndex]['Motor Command']

		watts = round(volt*amp  , 1 )
		if not watts: continue
		y.append(round(thrust, 2)/watts )
		x.append(throttle)

	return x, y

def getThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=1)
	tSmooth = smoother(avgTaps=5, medTaps=29)
	for sampleIndex in index['Thrust']:
		rpm = sample[sampleIndex]['RPMF']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustF']
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
	#smooth = smoother(avgTaps=5, medTaps=100, preAvgTaps=20)
	#smooth = smoother(avgTaps=1, medTaps=1, preAvgTaps=1)
	#smooth = KalmanFilter(.01, 100)




	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustF']
		#smooth.add( thrust )
		y.append( thrust )
		#smoothedValue =  round(smooth.get(), 4 )
		x.append( util.getFloatTime(time) )
		#y.append(smoothedValue)

	return x, y

def getIdleThrust(sample, index):

	samples = []
	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustF']
		if  util.getFloatTime(time) > 1:
			break
		samples.append(thrust)

	if samples:
		return numpy.median(samples)

	return None



def getTestThrustResidual(sample, index):
	# thrust / RPM
	x = []
	y = []

	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustResidual']
		y.append( thrust )
		x.append( util.getFloatTime(time) )

	return x, y

def getThrottleThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=3)
	for sampleIndex in index['Thrust']:
		throttle = sample[sampleIndex]['Motor Command']
		thrust = sample[sampleIndex]['Thrust']
		smooth.add( thrust )
		smoothedValue =  round(smooth.get(), 3 )
		x.append(throttle )
		y.append(smoothedValue)
	return x, y

def getRpmOverThrottle(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=2, medTaps=1)

	for sampleIndex in index['RPM']:
		throttle = sample[sampleIndex]['Motor Command']
		rpm = sample[sampleIndex]['RPM']
		if rpm > 65000: 
			continue
		x.append( throttle )
		smooth.add( rpm )
		thisValue = smooth.get()
		y.append(rpm)
	return x, y

def getTestRpm(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=2, medTaps=1)
	dsmooth = smoother(avgTaps=2, medTaps=1)

	lastGoodTime = 0
	lastValue = 0
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPMF']
		x.append( util.getFloatTime(time) )
		smooth.add( rpm )
		thisValue = smooth.get()
		if deltaMode:
			dsmooth.add( float(thisValue-lastValue)/(float(time-lastGoodTime)/1000)  )
			y.append( dsmooth.get() )
			lastGoodTime = time
			lastValue = thisValue
		else:
			y.append(rpm)
	return x, y

def getTestRpmError(sample, index, deltaMode=False):
	x = []
	y = []

	for sampleIndex in index['autoCalibrate']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['autoCalibrate']
		x.append( util.getFloatTime(time) )
		y.append(volt)
	return x, y

def getTestVoltsRaw(sample, index):
	x = []
	y = []

	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		x.append( util.getFloatTime(time) )
		y.append(volt)
	return x, y

def getTestTRaw(sample, index, deltaMode=False, sensor='T1'):
	x = []
	y = []
	lastGoodTime = 0
	lastValue = 0
	dsmooth = smoother(avgTaps=70, medTaps=5)
	smooth = smoother(avgTaps=1, medTaps=5)

	for sampleIndex in index[sensor]:
		time = sample[sampleIndex]['Time']
		T = sample[sampleIndex][sensor]
		x.append( util.getFloatTime(time) )


		if deltaMode:
			dsmooth.add( 1000*(float(T-lastValue)/(float(time-lastGoodTime)/1000))  )
			y.append( dsmooth.get() )
			lastGoodTime = time
			lastValue = T
		else:
			#smooth.add(T)
			y.append(T)

	return x, y

def getThrustOverT1(sample, index):
	x = []
	y = []
	for sampleIndex in index['Thrust']:
		T1 = sample[sampleIndex]['T1']
		thrust = sample[sampleIndex]['Thrust']
		x.append(T1 )
		y.append(thrust)
	return x, y

def getThrustOverV(sample, index):
	x = []
	y = []
	for sampleIndex in index['Thrust']:
		volt = sample[sampleIndex]['Volt']
		thrust = sample[sampleIndex]['Thrust']
		x.append(volt )
		y.append(thrust)
	return x, y

def getCommandRaw(sample, index, trace='Motor'):
	x = []
	y = []
	for sampleIndex in index[trace+' Command']:
		time = sample[sampleIndex]['Time']
		T1 = sample[sampleIndex][trace+' Command']
		x.append( util.getFloatTime(time) )
		y.append(T1)
	return x, y

def getTestAmpsRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		x.append( util.getFloatTime(time) )
		y.append(amp)
	return x, y

def getTestVolts(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=24, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		smooth.add( volt )
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append( util.getFloatTime(time) )
			y.append(sample[sampleIndex]['VoltF'])
			lastTime = time
	return x, y

def getTestAmps(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=24, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		smooth.add( amp )
				
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append( util.getFloatTime(time) )
			y.append(sample[sampleIndex]['AmpF'])
			lastTime = time
	return x, y

def getTestRpmRAW(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	lastGoodTime=0
	lastValue=0
	for sampleIndex in index['RPMRAW']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPMRAW']
		x.append( util.getFloatTime(time) )

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

		if value > 60000: continue
		x.append( util.getFloatTime(time) )
		smooth.add( value )
		smootedValue = round(smooth.get(), 3 )
		if sampleIndex >= len(unloadedRPM): continue
		if unloadedRPM[sampleIndex]==None: continue 
		y.append(100- (smootedValue/unloadedRPM[sampleIndex])*100 )
	return x, y

def getUnloadedBaseline(logPath):
	sample, index = readBinaryLog(logPath)

	unloadedRPM = [None]*len(sample)
	unloadedIndex = []
	smooth = smoother(avgTaps=4, medTaps=1)
	for sampleIndex in index['RPM']:
		value = sample[sampleIndex]['RPM']

		if value > 60000: continue
		smooth.add( value )
		unloadedRPM[sampleIndex] = round(smooth.get(), 3 )
		unloadedIndex.append(sampleIndex)

	getInterpolated(unloadedIndex, unloadedRPM)
	return unloadedRPM

def createPropDump(sample, index):
	maxCommand = 2000
	targetCommands = [ maxCommand*(i/100.0) for i in range(5,105,5) ]
	lastCommandIndex = 0
	dump = []
	for i in range(len(index['Motor Command'])):
		sampleIndex = index['Motor Command'][i]
		command = sample[sampleIndex]['Motor Command']

		if command >= targetCommands[lastCommandIndex]:
			rpm = sample[sampleIndex]['RPMF']
			thrust = sample[sampleIndex]['ThrustF']
			print 'threshold', command, rpm

			thisDump = {}
			thisDump['rpm']=rpm
			thisDump['thrust']=thrust
			thisDump['torque']=-1
			thisDump['command']=command

			dump.append(thisDump)

			lastCommandIndex = lastCommandIndex+1
			if lastCommandIndex >= len(targetCommands):
				break

	dumpFile = open('last.prop', 'w')
	json.dump(dump, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
	dumpFile.close()

	return dump

def integratePropDump(sample, index, dump):
	x = []
	y = []
	z = []
	command = []
	inWatts = []

	thisProgramName = sample[0]['programName']
	nameSplit = thisProgramName.split('_')
	throttleValue = float(nameSplit[0])
	thisDumpEntry = None

	print 'starting with dump', dump
	for item in dump:
		print 'item', item
		if item['command']==(throttleValue/100)*2000:
			print 'found dump entry', item
			thisDumpEntry = item
			break

	targetRPM = thisDumpEntry['rpm']
	tolerance = 100

	torqueAcc = []
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if roundedTime<dynoStartTime-dynoPreLoad: continue
		if roundedTime>dynoEndTime: continue

		if sampleIndex not in index['Thrust']: continue

		thisTorque = sample[sampleIndex]['ThrustF']*100 # convert Nm to Ncm
		if roundedTime<dynoStartTime: continue

		rpm = sample[sampleIndex]['RPMF']

		if not rpm: continue

		tolerance = targetRPM * 0.0025
		if ((rpm > targetRPM-tolerance) and (rpm < targetRPM+tolerance)):
			torqueAcc.append( thisTorque)
		
	print 'averaging', len(torqueAcc)

	if not torqueAcc: return dump

	averageTorque = sum(torqueAcc)/len(torqueAcc)
	thisDumpEntry['torque']=averageTorque
	thisDumpEntry['torqueCnt']=len(torqueAcc)

	dumpFile = open('lastIntegrate.prop', 'w')
	json.dump(dump, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
	dumpFile.close()

	return dump



def buildFigure(dataList, labelList, deltaMode, chartTitle=None, mode=None, patchLoad=None):
	colorsSource = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'green', 'blue','red']
	colors = copy.copy(colorsSource)
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']
	if deltaMode:
		yScale = labelList['yScaleDelta']
	
	deltaString = ''
	if deltaMode:
		deltaString = ' - Delta'

	outputFile = './output/'+mode+deltaString+'.html'
	outputTitle = mode+deltaString
	if chartTitle:
		outputTitle = chartTitle

	output_file( outputFile, title=outputTitle, mode='inline' )

	foundZ = False

	for item in dataList[::-1]:
		if item['extraData']:
			foundZ = True
	tooltipList = [
			#("index", "$index"),
			(xLabel, "@x{1.11}"),
			(yLabel, "@y{1.11}"),
		]

	if foundZ:
		tooltipList.append(('eff', "@z{1.11}") )
		tooltipList.append(('power', "@inWatts{1.11}") )
		tooltipList.append(('command', "@command{1.11}") )

	hover = HoverTool(
		tooltips = tooltipList,
		#mode='vline',
	)



	p = figure(
		width=1520, plot_height=880,
		tools=[hover,'pan','box_zoom','wheel_zoom', 'reset','crosshair', 'tap'],#"resize,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
		active_scroll='wheel_zoom',
		y_range=[0, yScale],
		#y_range=None,
		x_axis_label=xLabel,# y_axis_label=yLabel,
		output_backend="webgl",
		title=outputTitle
	)
	

	#defaultRange = 'default_range'
	#p.extra_y_ranges.update( {defaultRange: Range1d(start=0, end=yScale)} )
	#p.add_layout(LinearAxis(y_range_name=defaultRange,  axis_label=yLabel), 'left')


	#mapperColors = ["#75968f", "#a5bab7", "#c9d9d3", "#e2e2e2", "#dfccce", "#ddb7b1", "#cc7878", "#933b41", "#550b1d"]
	#mapperColors = ["#d7191c", "#D3272D", "#CD3C46", "#C45E6F", "#BA8098", "#b0a3c2", "#929FC9", "#6C99D2", "#4694DB", "#3791DF", "#198de6"]
	#mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	#mapperColors = ["#d7191c",  "#ff0000",  "#000000",  "#00ff00", "#198de6"]
	mapper = LinearColorMapper(palette=mapperColors, low=.0, high=1)
	mapperLegend = LinearColorMapper(palette=mapperColors, low=.0, high=100)

	if outputTitle == 'Torque Over RPM':
		allRanges = []
		for item in dataList:
			if '_' not in item['programName']: continue
			throttleValue = int(item['programName'].split('_')[0])
			smooth = smoother(avgTaps=3, medTaps=1)
			smoothT = smoother(avgTaps=1, medTaps=3)
			newZ = []
			newY = []


			for value in item['extraData']['z']:
				smooth.add(value)
				newZ.append( smooth.get() )
			count = 0
			for value in item['y']:
				smoothT.add(value)
				#if value < 0: print 'under',  smoothT.get(), smoothT.medAcc, smoothT.avgAcc, count
				count = count +1
				newY.append( smoothT.get() )
			#item['z']=newZ

			range = {}
			topValue = newZ[-1]
			band = int(topValue*10)
			range[band]={}
			range['throttleValue']=throttleValue

			range[band]['start']=[item['x'][-1],newY[-1]]
			#for index in xrange(band, -1, -1):
			for index in xrange(0,band, 1):
				range[index]={}
				range[index]['start']=[item['x'][-1],newY[-1]]
				range[index]['end']=[item['x'][-1],newY[-1]]

			for index in xrange(len(item['extraData']['z'] )-1, -1, -1): # count top down
			#for index in xrange(0, len(item['z'] ), 1): # count bottom up
				thisValue = item['extraData']['z'][index]
				if thisValue > 1: continue
				if int(thisValue*10) > band:
					range[band]['end']=[item['x'][index],newY[index]]
					band = int(thisValue*10)
					range[band]={}
					range[band]['start']=[item['x'][index],newY[index]]
			range[band]['end']=[item['x'][0],newY[0]]

			for index in xrange(band+1, 11 ):
				range[index]={}
				range[index]['start']=[item['x'][0],newY[0]]
				range[index]['end']=[item['x'][0],newY[0]]
			allRanges.append(range)
			#item['range'] = range

		allMin = 10
		for range in allRanges:
			allMin = min(min(range.keys()), allMin)

		shapeCoords = {}
		for shapeRange in xrange(0,11):
			for range in allRanges:
				thisMin = min(range.keys())
				thisMax = max(range.keys())
				if shapeRange not in range.keys():
					continue
					range[shapeRange] = {}
					if shapeRange<thisMin:
						range[shapeRange]['start'] = range[thisMin]['start']
						range[shapeRange]['end'] = range[thisMin]['start']
					else:
						range[shapeRange]['start'] = range[thisMax]['end']
						range[shapeRange]['end'] = range[thisMax]['end']
				if shapeRange not in shapeCoords.keys():
					shapeCoords[shapeRange] = []
				shapeCoords[shapeRange].append( [range[shapeRange]['start'], range[shapeRange]['end'], range['throttleValue']] )

		patches = {}
		patchDump = {}

		for index in shapeCoords:
			shapeCoords[index].sort(key=lambda x: x[2]  )

		for shapeRange in shapeCoords.keys():
			patches[shapeRange] = {}
			patchDump[shapeRange] = []
			patches[shapeRange]['x']=[]
			patches[shapeRange]['y']=[]

			for index in xrange(0, len(shapeCoords[shapeRange])):
				x = int(shapeCoords[shapeRange][index][0][0])
				y = round(shapeCoords[shapeRange][index][0][1],4)
				patches[shapeRange]['x'].append( x )
				patches[shapeRange]['y'].append( y )
				patchDump[shapeRange].append( [x,y] )

			for index in xrange(len(shapeCoords[shapeRange])-1, -1, -1):
				x = int(shapeCoords[shapeRange][index][1][0])
				y = round(shapeCoords[shapeRange][index][1][1],4)
				patches[shapeRange]['x'].append( x )
				patches[shapeRange]['y'].append( y )
				patchDump[shapeRange].append( [x,y] )

		patchFile = open('last.patch', 'w')
		json.dump(patchDump, patchFile, sort_keys=True, indent=4, separators=(',', ': '))
		patchFile.close()

	if patchLoad:
		patches = {}
		#for shapeRange in sorted(patchLoad.keys()):
		for shapeRange in xrange(9,0,-1):
			print 'getting shapeRange', shapeRange
			patches[shapeRange] = {}
			patches[shapeRange]['x']=[]
			patches[shapeRange]['y']=[]
			if not patchLoad[shapeRange]: continue

			for index in xrange(0, len(patchLoad[shapeRange])):
				print 'index', shapeRange, index
				patches[shapeRange]['x'].append( patchLoad[shapeRange][index][0] )
				patches[shapeRange]['y'].append( patchLoad[shapeRange][index][1] )

			tempRange = patchLoad[shapeRange+1]
			if patchLoad[shapeRange][0] in tempRange:
				tempRange = tempRange[ tempRange.index(patchLoad[shapeRange][0]): ]
			if patchLoad[shapeRange][-1] in tempRange:
				tempRange = tempRange[ : tempRange.index(patchLoad[shapeRange][-1])]

			for index in xrange(len(tempRange)-1, -1, -1):

				print 'index',shapeRange+1, index

				patches[shapeRange]['x'].append( tempRange[index][0] )
				patches[shapeRange]['y'].append( tempRange[index][1] )

	allScatter = []

	for item in dataList[::-1]:
		if not colors:
			colors = copy.copy(colorsSource)

		print 'creating plot for', item['label'], item['mode']
		#thisRange = defaultRange
		rangeArgs = {}
		if item['extraRange']:
			rangeName = item['label'] + '_range'
			p.extra_y_ranges.update( {rangeName: Range1d(start=0, end=item['extraRange'])} )
			p.add_layout(LinearAxis(y_range_name=rangeName, axis_label=item['extraLabel']), 'left')
			#thisRange = rangeName
			rangeArgs['y_range_name']=rangeName

		data = {
			'x':item['x'],
			'y':item['y']
			}

		if item['extraData']:
			data['z']= item['extraData']['z']
			if 'inWatts' in  item['extraData'].keys(): 
				data['inWatts']= item['extraData']['inWatts']
				data['command']= item['extraData']['command']
				data['scatterSize']=[i * 8 for i in item['extraData']['z']]
				data['color']=[i  for i in item['extraData']['z']]



		source = ColumnDataSource( data=data)

		if item['mode']=='line':
			p.line('x', 'y', source=source, legend=item['label'], color=colors.pop(), line_width=3, *rangeArgs)

		else:
			scatterSize = 8
			if item['extraData']:
				#scatterSize = 'scatterSize'
				thisColor = {'field': 'z', 'transform': mapper}
			else:
				thisColor = colors.pop()
			thisScatter = p.scatter('x', 'y', source=source, legend=item['label'], color=thisColor, size=scatterSize, *rangeArgs)
			allScatter.append(thisScatter)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"

	if (outputTitle == 'Torque Over RPM') or (patchLoad):
		color_bar = ColorBar(color_mapper=mapperLegend, major_label_text_font_size="8pt",
                     ticker=BasicTicker(desired_num_ticks=len(colors)),
                     formatter=PrintfTickFormatter(format="%d%%"),
                     label_standoff=6, border_line_color=None, 
                     height=500, location=(-80, 0))
		p.add_layout(color_bar, 'right')

		for index in patches:
			if index>len(mapperColors)-1:
				thisColor = mapperColors[-1]
			else:
				thisColor = mapperColors[index]
			p.patch( patches[index]['x'], patches[index]['y'], alpha=0.5, line_width=2, fill_color=thisColor)

	callback = CustomJS(code="""
	// the event that triggered the callback is cb_obj:
	// The event type determines the relevant attributes
	if (typeof coords == 'undefined') {
		coords = [];
	}
	coords.push( [ Math.round(cb_obj.x), +cb_obj.y.toFixed(2) ] );
	console.log('Tap event occured at x-position: ' + cb_obj.x + ', '+ cb_obj.y);
	""")

	tapCallback = CustomJS(code="""
	if (typeof coords == 'undefined') {
		coords = [];
	}
	var srcIndex = cb_data.source.selected['1d'].indices[0];
	var d1 = cb_data.source.data;
	var x = d1['x'][srcIndex];
	var y = d1['y'][srcIndex];
	console.log('TapTool event occured at x-position: ' + x + ', '+ y);
	coords.push( [ Math.round(x), +y.toFixed(2) ] );

	""")

	#p.js_on_event(events.Tap, callback)

	taptool = p.select(type=TapTool)
	taptool.callback = tapCallback

	sliderCallback = CustomJS(args=dict(source=source, xRange=p.x_range, yRange=p.y_range), code="""
	var xMin = parseFloat(xMinInput.value);
	var xMax = parseFloat(xMaxInput.value);
	var yMin = parseFloat(yMinInput.value);
	var yMax = parseFloat(yMaxInput.value);

	xRange.start = xMin;
	xRange.end = xMax;

	yRange.start = yMin;
	yRange.end = yMax;
	""")

	bookmarkCallback = CustomJS(args=dict(source=source, xRange=p.x_range, yRange=p.y_range), code="""
	var bookmarkString = bookmarkInput.value;
	var stringSplit = bookmarkString.split(":");
	var xMin = parseFloat(stringSplit[0]);
	var xMax = parseFloat(stringSplit[1]);
	var yMin = parseFloat(stringSplit[2]);
	var yMax = parseFloat(stringSplit[3]);

	xRange.start = xMin;
	xRange.end = xMax;

	yRange.start = yMin;
	yRange.end = yMax;
	""")

	sizeCallback = CustomJS(args=dict( plot=p ), code="""
	var size = parseFloat(sizeInput.value);
	allRenderers = plot.renderers;

	for (var index in allRenderers) {
		item = allRenderers[index];
		if ('y_range_name' in item){
			if (item.y_range_name == "default"){
				if ('glyph' in item){
					item.glyph.size=size;
				}
			}
		}
	}
	""")

	yMaxInput = widgets.TextInput(value="8", title="Ymax", callback=sliderCallback)
	sliderCallback.args['yMaxInput']=yMaxInput
	yMinInput = widgets.TextInput(value="0", title="Ymin", callback=sliderCallback)
	sliderCallback.args['yMinInput']=yMinInput
	xMaxInput = widgets.TextInput(value="40000", title="xmax", callback=sliderCallback)
	sliderCallback.args['xMaxInput']=xMaxInput
	xMinInput = widgets.TextInput(value="0", title="xmin", callback=sliderCallback)
	sliderCallback.args['xMinInput']=xMinInput
	bookmarkInput = widgets.TextInput(value="", title="bookmark", callback=bookmarkCallback)
	sliderCallback.args['bookmarkInput']=bookmarkInput
	bookmarkCallback.args['bookmarkInput']=bookmarkInput
	sizeInput = widgets.TextInput(value="", title="size", callback=sizeCallback)
	sizeCallback.args['sizeInput']=sizeInput

	xMinChangeCB = CustomJS(args=dict(source=source, xRange=p.x_range, yRange=p.y_range, 
		xMinInput=xMinInput, xMaxInput=xMaxInput, yMinInput=yMinInput, yMaxInput=yMaxInput, bookmarkInput=bookmarkInput), code="""
	xMinInput.value = xRange.start.toString();
	xMaxInput.value = xRange.end.toString();
	yMinInput.value = yRange.start.toString();
	yMaxInput.value = yRange.end.toString();
	bookmarkInput.value = xRange.start.toString()+":"+ xRange.end.toString()+":"+ yRange.start.toString() + ":" + yRange.end.toString();
	""")

	p.x_range.js_on_change('start', xMinChangeCB)
	p.x_range.js_on_change('end', xMinChangeCB)
	p.y_range.js_on_change('start', xMinChangeCB)
	p.y_range.js_on_change('end', xMinChangeCB)


	layout = row(
		p,
		widgetbox(xMinInput, xMaxInput, yMinInput, yMaxInput, bookmarkInput, sizeInput),
	)


	show(layout)
	reset_output()

