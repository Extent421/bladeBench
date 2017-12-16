peakLoad = 90
steps = 20

halfLoad = peakLoad * .75
increment = 100/steps

for i in xrange(1, steps+1):
	currentStep = i*increment

	halfStep = currentStep * .5
	if halfStep < 5.0: halfStep = 5.0


	program = \
'''hold 0.0 0.0 1s
hold 7.0 0.0 2s
tach 7.0 2s
ramp {step:.1f} 0.0 3s
ramp {step:.1f} 25.0 1s
ramp {step:.1f} {load:.1f} 4s
ramp 0 {load:.1f} 500ms
hold 0.0 0.0 2s
'''.format(load=peakLoad, step=currentStep, halfLoad=halfLoad, halfStep=halfStep)

	f = open('./programs/'+str(currentStep)+'_'+str(peakLoad)+'.txt', 'w' )
	f.write(program)
	f.close()