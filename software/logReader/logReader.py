import csv
import copy
import math
import json

import webbrowser
import os

from bokeh.plotting import figure, output_file, show, reset_output, ColumnDataSource
from bokeh.models import HoverTool, Range1d, LinearAxis, LinearColorMapper, ColorBar, BasicTicker, PrintfTickFormatter, CustomJS, TapTool, Slider, widgets
from bokeh.layouts import row, widgetbox
from bokeh import events
import bokeh

import numpy.polynomial.polynomial as poly
import numpy


from . import parseV3
from . import parseV4
from . import util
from . import filters
from . import chartBuilder

dynoStartTime = 9.25
dynoEndTime = 12.8
dynoEndTime = 12.85
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

class bladeBenchLog():
	filePath = None
	headerValues = {}

	def __init__(self, filePath ):
		self.filePath = filePath
		self.readHeader()

	def readHeader(self):
		with open(self.filePath, 'rb') as f:

			for line in iter(f.readline, ''):
				if 'adcMaxValue:' in line:
					self.headerValues['adcMax'] = float(line.split(':')[-1])
				if 'vref:' in line:
					self.headerValues['vref'] = float(line.split(':')[-1])
				if 'thermBValue:' in line:
					self.headerValues['thermBValue'] = float(line.split(':')[-1])
				if 'pulse per rev:' in line:
					self.headerValues['pulse per rev'] = int(line.split(':')[-1])
				if 'loadcell calibration value:' in line:
					self.headerValues['loadcell calibration value'] = float(line.split(':')[-1])

				if 'vrange:' in line:
					if '6s' in line.split(':')[-1]:
						self.headerValues['vrange']='6s'
					else:
						self.headerValues['vrange']='3s'

				if 'vCalibrate:' in line:
					self.headerValues['vCalibrate'] = float(line.split(':')[-1])
				if 'vOffset:' in line:
					self.headerValues['vOffset'] = float(line.split(':')[-1])
				if 'aCalibrate:' in line:
					self.headerValues['aCalibrate'] = float(line.split(':')[-1])
				if 'aOffset:' in line:
					self.headerValues['aOffset'] = float(line.split(':')[-1])

				if 'motorPully:' in line:
					self.headerValues['motorPully'] = float(line.split(':')[-1])
				if 'drivePully:' in line:
					self.headerValues['drivePully'] = float(line.split(':')[-1])

				if 'loaded program:' in line:
					self.headerValues['loaded program'] = line.split(':')[-1].strip()

				if line == 'Data Start:\n':
					self.headerValues['data start'] = f.tell()
					break

	def getProgramName(self):
		if 'loaded program' in self.headerValues.keys():
			return self.headerValues['loaded program']


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
	inVolts = []

	global dynoStartTime, dynoEndTime
	dynoStartTime = 3
	dynoEndTime = 99
	thisProgramName = sample[0]['programName']
	
	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				dynoStartTime = util.getFloatTime(sample[sampleIndex]['Time'])
			if sample[sampleIndex]['Marker'] == 2:
				dynoEndTime = util.getFloatTime(sample[sampleIndex]['Time'])

	minThrust = None
	minThrustIndex = None
	minRpm = None
	minRpmIndex =None

	for sampleIndex in index['Time']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if roundedTime<dynoStartTime-dynoPreLoad: continue
		if roundedTime>dynoEndTime: break

		if not minThrust:
			minThrust = sample[sampleIndex]['ThrustF']
			minThrustIndex = sampleIndex

		if not minRpm:
			minRpm = sample[sampleIndex]['RPM']
			minRpmIndex = sampleIndex

		if sample[sampleIndex]['ThrustF'] < minThrust:
			minThrust = sample[sampleIndex]['ThrustF']
			minThrustIndex = sampleIndex

		if sample[sampleIndex]['RPMF'] < minRpm:
			minRpm = sample[sampleIndex]['RPMF']
			minRpmIndex = sampleIndex


	print 'range indexes', minThrustIndex, minRpmIndex
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if sampleIndex>minRpmIndex: break
		if sampleIndex<minThrustIndex: continue

		volt = sample[sampleIndex]['VoltF']
		amp = sample[sampleIndex]['AmpF']

		#if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['ThrustF']+idleOffset

		rpm = sample[sampleIndex]['RPMF']

		if not rpm: continue
		
		mechWatts = thrust * (rpm * ((2*math.pi)/60) )
		watts = volt*amp
		if not watts: continue

		y.append(round(thrust, 4) )
		x.append(rpm)
		z.append(round(mechWatts/watts, 2) )
		inWatts.append(round(watts, 1) )
		inVolts.append(round(volt, 2) )
		command.append(sample[sampleIndex]['Motor Command'] )

	accX = []
	accY = []
	accZ = []
	accInWatts = []
	accInVolts = []

	'''
	extraData = {}
	extraData['z'] = z
	extraData['inWatts'] = inWatts
	extraData['command'] = command

	return x, y, extraData, thisProgramName
	'''

	mergedX = []
	mergedY = []
	mergedZ = []
	mergedCommand = []
	mergedInWatts = []
	mergedInVolts = []
	lastValue = y[0]
	lastIndex = 0
	maxDist = 1000
	#maxDist = 250

	#preload the merged result with the actual highest RPM sample
	mergedCommand.append(command[0])
	mergedX.append(x[0])
	mergedY.append(y[0])
	mergedZ.append(z[0])
	mergedInWatts.append(inWatts[0])
	mergedInVolts.append(inVolts[0])


	#reduce point count based on segment distance
	for index in range(0,len(x)):
		xDist = x[index] - x[lastIndex]
		yDist = ( y[index] - y[lastIndex] )*1000000
		thisDist = abs( math.sqrt( pow(xDist,2) + pow(yDist,2) ) )

		if thisDist > maxDist:
			mergedCommand.append(command[index])
			mergedX.append(numpy.mean(accX))
			mergedY.append(numpy.mean(accY))
			mergedZ.append(numpy.mean(accZ))
			mergedInWatts.append(numpy.mean(accInWatts))
			mergedInVolts.append(numpy.mean(accInVolts))
			accX = []
			accY = []
			accZ = []
			accInWatts = []
			accInVolts = []
			lastIndex = index

		accX.append(x[index])
		accY.append(y[index])
		accZ.append(z[index])
		accInWatts.append(inWatts[index])
		accInVolts.append(inVolts[index])


	mergedCommand.append(command[index])
	mergedX.append(numpy.mean(accX))
	mergedY.append(numpy.mean(accY))
	mergedZ.append(numpy.mean(accZ))
	mergedInWatts.append(numpy.mean(accInWatts))
	mergedInVolts.append(numpy.mean(accInVolts))

	extraData = {}
	extraData['z'] = mergedZ
	extraData['inWatts'] = mergedInWatts
	extraData['inVolts'] = mergedInVolts
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

	testStartTime = 3
	testEndTime = 99
	
	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				testStartTime = util.getFloatTime(sample[sampleIndex]['Time'])
			if sample[sampleIndex]['Marker'] == 2:
				testEndTime = util.getFloatTime(sample[sampleIndex]['Time'])

	for sampleIndex in index['Thrust']:
		rpm = sample[sampleIndex]['RPMF']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustF']
		if not rpm: continue

		roundedTime = util.getFloatTime(time) 

		if roundedTime<testStartTime: continue
		if roundedTime>testEndTime: break



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

	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['ThrustF']
		y.append( thrust )
		x.append( util.getFloatTime(time) )

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

def getInertia(sample, index, torqueLoad, propLoad):
	x = []
	y = []

	thisStaticTorque = 0

	inertiaStart = 0
	inertiaEnd = 99

	
	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				inertiaStart = util.getFloatTime(sample[sampleIndex]['Time']) + 0.005
				inertiaEnd = inertiaStart + 0.020
				inertiaEnd = inertiaStart + 0.045
				inertiaEnd = inertiaStart + 1


	for i in xrange( 1,len(index['RPM']) ):
		sampleIndex = index['RPM'][i]
		thisTime = sample[sampleIndex]['Time']

		roundedTime = util.getFloatTime(thisTime) 
		if roundedTime<inertiaStart: continue
		if roundedTime>inertiaEnd: break


		lastTime = sample[sampleIndex-1]['Time']
		thisRPM = sample[sampleIndex]['RPMF']
		lastRPM = sample[sampleIndex-1]['RPMF']
		thisCommand = sample[sampleIndex]['Motor Command']
		throttle = int(round( (thisCommand/2000.0) * 100))

		if throttle not in torqueLoad.keys():
			continue
		found = False
		for j in xrange( len( torqueLoad[throttle] ) ):
			if torqueLoad[throttle][j]['rpm']> thisRPM:
				found=True
				break

		if not found:
			print 'no torque found', thisRPM, 'on', throttle
			continue

		if propLoad:
			found = False
			for k in xrange( len( propLoad ) ):
				if propLoad[k]['rpm']> thisRPM:
					found=True
					break
		
			if not found:
				print 'no prop torque found', thisRPM
				continue

			propRPMA = propLoad[k]['rpm']
			propRPMB = propLoad[k-1]['rpm']
			propTorqueA = propLoad[k]['torque']
			propTorqueB = propLoad[k-1]['torque']
			interpDist = (thisRPM-propRPMA)/(propRPMB-propRPMA)
			thisStaticTorque = propTorqueA + (propTorqueB - propTorqueA)*interpDist


		RPMA = torqueLoad[throttle][j]['rpm']
		RPMB = torqueLoad[throttle][j-1]['rpm']
		torqueA = torqueLoad[throttle][j]['torque']
		torqueB = torqueLoad[throttle][j-1]['torque']


		interpDist = (thisRPM-RPMB)/(RPMA-RPMB)
		thisTotalTorque = torqueB + (torqueA - torqueB)*interpDist

		accelTorque = thisTotalTorque - thisStaticTorque

		timeDelta = util.getFloatTime( thisTime - lastTime )
		RPMDelta = thisRPM - lastRPM

		accel = RPMDelta/timeDelta

		accelRadian = (math.pi/30) * accel
		torqueNm = accelTorque/100
		inertia = torqueNm/accelRadian # in kg m^2
		inertiaG = inertia*pow(10, 7) # in g cm^2
		#T=I*A
		#T/A = I
		if inertiaG > 200: continue
		if inertiaG < 0: continue

		x.append( util.getFloatTime(thisTime) )
		y.append(inertiaG)

	if len(y)>6:
		print 'Y length', len(y)
		y = filters.butterFilter(y, order = 1, cutoff = 0.5 ) 
	
	return x, y

def getInertiaSingle(sample, index):
	x = []
	y = []

	thisStaticTorque = 0

	inertiaStart = 0
	inertiaEnd = 99

	
	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				inertiaStart = util.getFloatTime(sample[sampleIndex]['Time']) + 0.005
				inertiaEnd = inertiaStart + 0.020
				inertiaEnd = inertiaStart + 0.045
				inertiaEnd = inertiaStart + 1

	for i in xrange( 1,len(index['RPM']) ):
		sampleIndex = index['RPM'][i]
		thisTime = sample[sampleIndex]['Time']

		roundedTime = util.getFloatTime(thisTime) 
		if roundedTime<inertiaStart: continue
		if roundedTime>inertiaEnd: break


		lastTime = sample[sampleIndex-1]['Time']
		thisRPM = sample[sampleIndex]['RPMF']
		lastRPM = sample[sampleIndex-1]['RPMF']
		thisCommand = sample[sampleIndex]['Motor Command']
		throttle = int(round( (thisCommand/2000.0) * 100))


		accelTorque = sample[sampleIndex]['ThrustF']

		timeDelta = util.getFloatTime( thisTime - lastTime )
		RPMDelta = thisRPM - lastRPM

		accel = RPMDelta/timeDelta

		accelRadian = (math.pi/30) * accel
		torqueNm = accelTorque
		inertia = torqueNm/accelRadian # in kg m^2
		inertiaG = inertia*pow(10, 7) # in g cm^2
		#T=I*A
		#T/A = I
		if inertiaG > 200: continue
		if inertiaG < 0: continue

		x.append( util.getFloatTime(thisTime) )
		y.append(inertiaG)

	if len(y)>6:
		print 'Y length', len(y)
		y = filters.butterFilter(y, order = 1, cutoff = 0.5 ) 
	
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

def integratePropDump(sample, index, dump,  idleOffset=0):
	x = []
	y = []
	z = []
	command = []
	inWatts = []

	thisProgramName = sample[0]['programName']
	nameSplit = thisProgramName.split('_')
	throttleValue = float(nameSplit[0])
	thisDumpEntry = None

	print 'starting with dump, searching for',(throttleValue/100)*2000
	for item in dump:
		if item['command']==(throttleValue/100)*2000:
			print 'found dump entry', item
			thisDumpEntry = item
			break

	if not thisDumpEntry: return dump

	targetRPM = thisDumpEntry['rpm']
	tolerance = 200


	torqueAcc = []
	minThrust = None
	minThrustIndex = None
	minRpm = None
	minRpmIndex =None

	global dynoStartTime, dynoEndTime

	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				dynoStartTime = util.getFloatTime(sample[sampleIndex]['Time'])+.5
			if sample[sampleIndex]['Marker'] == 2:
				dynoEndTime = util.getFloatTime(sample[sampleIndex]['Time'])-.05

	print 'start/end', dynoStartTime, dynoEndTime

	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if roundedTime<dynoStartTime-dynoPreLoad: continue
		if roundedTime>dynoEndTime: break

		if not minThrust:
			minThrust = sample[sampleIndex]['ThrustF']
			minThrustIndex = sampleIndex

		if not minRpm:
			minRpm = sample[sampleIndex]['RPM']
			minRpmIndex = sampleIndex

		if sample[sampleIndex]['ThrustF'] < minThrust:
			minThrust = sample[sampleIndex]['ThrustF']
			minThrustIndex = sampleIndex

		if sample[sampleIndex]['RPMF'] < minRpm:
			minRpm = sample[sampleIndex]['RPMF']
			minRpmIndex = sampleIndex

	print minThrust, minThrustIndex, util.getFloatTime(sample[minThrustIndex]['Time']), minRpm, minRpmIndex,  util.getFloatTime(sample[minRpmIndex]['Time'])


	foundExact = None

	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 

		if sampleIndex>minRpmIndex: break
		if sampleIndex<minThrustIndex: continue


		thisTorque = (sample[sampleIndex]['ThrustF']+idleOffset)*100 # convert Nm to Ncm
		rpm = sample[sampleIndex]['RPMF']

		if not rpm: continue

		if (not foundExact) and (rpm < targetRPM):
			foundExact = thisTorque
			print 'found point', thisTorque, sample[sampleIndex]['Thrust']*100, sample[sampleIndex]['RPMF'], sample[sampleIndex]['RPM']
		tolerance = targetRPM * 0.005
		if ((rpm > targetRPM-tolerance) and (rpm < targetRPM+tolerance)):
			print 'found range', thisTorque,sample[sampleIndex]['RPM']
			torqueAcc.append( thisTorque)
		
	print 'averaging', len(torqueAcc)

	if not torqueAcc: return dump

	averageTorque = sum(torqueAcc)/len(torqueAcc)
	thisDumpEntry['torque']=foundExact
	thisDumpEntry['torqueCnt']=len(torqueAcc)

	dumpFile = open('lastIntegrate.prop', 'w')
	json.dump(dump, dumpFile, sort_keys=True, indent=4, separators=(',', ': '))
	dumpFile.close()

	return dump


def MQTBDump(sample, index):
	x = []
	y = []

	erpmPoleCount = 7
	sampleIncrement = 0.004
	lastTime = 0.0

	testStartTime = 0.0
	testStartUsec = 0
	if 'Marker' in index.keys():
		for sampleIndex in index['Marker']:
			if sample[sampleIndex]['Marker'] == 1:
				testStartTime = util.getFloatTime(sample[sampleIndex]['Time'])
				testStartUsec = sample[sampleIndex]['Time']


	import csv
	with open('mqtbDump.csv', 'wb') as csvFile:
		dumpWriter = csv.writer(csvFile)
		dumpWriter.writerow(['Time(uS)', 'Throttle(uS)', 'Thrust(g)', 'eSteps', 'eRPMs', 'Volts', 'Amps'])

		for sampleIndex in index['Volt']:

			time = sample[sampleIndex]['Time']
			floatTime = util.getFloatTime(time)
			if floatTime < testStartTime: 
				lastTime = floatTime
				continue

			throttle = (sample[sampleIndex]['Motor Command']/2)+1000
			thrust = round(sample[sampleIndex]['ThrustF'], 4)
			eSteps = 0
			rpm = round(sample[sampleIndex]['RPMSingle'])
			volt = round(sample[sampleIndex]['VoltF'], 4)
			amp = round(sample[sampleIndex]['AmpF'], 4)

			floatTime = util.getFloatTime(time)
			erpm = rpm * erpmPoleCount

			if floatTime > (lastTime+sampleIncrement):
				lastTime = lastTime+sampleIncrement
				dumpWriter.writerow([time-testStartUsec, throttle, thrust, eSteps, erpm, volt, amp])





	return x, y

def buildFigure(dataList, labelList, deltaMode, chartTitle=None, mode=None, patchLoad=None):
	colorsSource = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'green', 'blue','red']
	colors = copy.copy(colorsSource)
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']


	if deltaMode:
		yScale = labelList['yScaleDelta']


	figureArgs ={}
	figureArgs['y_range']=[0, yScale]
	#figureArgs['x_range']=[0, 40000]


	
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
		names=['propLine', 'scatterPlot']
		#mode='vline',
	)


	mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	mapper = LinearColorMapper(palette=mapperColors, low=.0, high=1)
	mapperLegend = LinearColorMapper(palette=mapperColors, low=.0, high=100)



	# load up the patch data, building the polygons for each efficiency range
	patches = {}
	patches['data'] = {}
	outsidePoints = []

	if not patchLoad:
		print 'creating default patch'
		patchLoad = {1: [[0, 0], [0, 0.001]], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: [], 10: []}
	
		patches, outsidePoints = chartBuilder.loadPatchDump(patchLoad)
	else:
		print 'using passed patch'
		patches, outsidePoints = chartBuilder.loadPatchDump(patchLoad)

		#if loading a patch file over ride the display range of the chart to fit
		figureArgs['y_range']=[0, patches['ymax']*1.1]
		figureArgs['x_range']=[0, patches['xmax']*1.15]

	allScatter = []

	print 'args', figureArgs

	p = figure(
		width=1520, plot_height=880,
		tools=[hover,'pan','box_zoom','wheel_zoom', 'reset','crosshair', 'tap'],#"resize,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
		active_scroll='wheel_zoom',
		#y_range=None,
		x_axis_label=xLabel,# y_axis_label=yLabel,
		output_backend="webgl",
		title=outputTitle,
		**figureArgs

	)


	if (outputTitle == 'Torque Over RPM') or (patchLoad):
		color_bar = ColorBar(color_mapper=mapperLegend, major_label_text_font_size="8pt",
                     ticker=BasicTicker(desired_num_ticks=len(colors)),
                     formatter=PrintfTickFormatter(format="%d%%"),
                     label_standoff=6, border_line_color=None, 
                     height=500, location=(-80, 0))
		p.add_layout(color_bar, 'right')

		if patches:
			chartBuilder.addPatchToChart(patches, outsidePoints, mapperColors, p)


			chartBuilder.findIntersections(dataList, outsidePoints, p)

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
			p.line('x', 'y', source=source, name='propLine', legend=item['label'], color=colors.pop(), line_width=3, *rangeArgs)

		else:
			scatterSize = 8
			if item['extraData']:
				#scatterSize = 'scatterSize'
				thisColor = {'field': 'z', 'transform': mapper}
			else:
				thisColor = colors.pop()
			thisScatter = p.scatter('x', 'y', source=source, name='scatterPlot', legend=item['label'], color=thisColor, size=scatterSize, *rangeArgs)
			allScatter.append(thisScatter)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"





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
	console.log(parseInt(patchIndexInput.value));
	var hitCoord = [ Math.round(x), y.toFixed(2) ] 
	coords.push( hitCoord );
	checkHit(hitCoord, parseInt(patchIndexInput.value) )
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

	patchIndexInput = widgets.TextInput(value="", title="patch index")
	tapCallback.args['patchIndexInput']=patchIndexInput

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
		widgetbox(xMinInput, xMaxInput, yMinInput, yMaxInput, bookmarkInput, sizeInput, patchIndexInput),

	)
	from jinja2 import Template

	template = Template('''<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <title>{{ title|e if title else "Bokeh Plot" }}</title>
        {{ bokeh_css }}
        {{ bokeh_js }}
        <script type="text/javascript" src="patchLoader.js"></script>
    </head>
    <body>
        {{ plot_div|indent(8) }}
        {{ plot_script|indent(8) }}
        <input type=button value="loadPatch" onclick="loadPatchFile()">
		<input type='button' value='download patch' onclick='dumpPatch();'>
		<input type='button' value='reset band' onclick='resetBand();'>
		<input type='button' value='reset all' onclick='resetAll();'>

        <form id="jsonFile" name="jsonFile" enctype="multipart/form-data" method="post">

		  <fieldset>
		    <h2>Json File</h2>
		     <input type='file' id='fileinput'>
		     <input type='button' id='btnLoad' value='Load' onclick='loadFile();'>
		  </fieldset>
		</form>
    </body>
</html>''')


	bokeh.io.save(layout)
	with open(outputFile, "w") as f: 
		f.write(bokeh.embed.file_html(layout, bokeh.resources.INLINE, template=template) ) 
	reset_output()

	webbrowser.open('file://' + os.path.realpath(outputFile))
