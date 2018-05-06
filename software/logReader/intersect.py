#
# line segment intersection using vectors
# see Computer Graphics by F.S. Hill
#
from numpy import *
import sys

def perp( a ) :
    b = empty_like(a)
    b[0] = -a[1]
    b[1] = a[0]
    return b

# line segment a given by endpoints a1, a2
# line segment b given by endpoints b1, b2
# return 
def intersectPoint( a1,a2, b1,b2 ) :
    a1 = array(a1)
    a2 = array(a2)
    b1 = array(b1)
    b2 = array(b2)
    da = a2-a1
    db = b2-b1
    dp = a1-b1
    dap = perp(da)
    denom = dot( dap, db)
    if not denom : return None
    num = dot( dap, dp )
    return (num / denom.astype(float))*db + b1

def isBetween( a, b, c):
    a = array(a)
    b = array(b)
    c = array(c)
    cma = c-a
    bma = b-a
    crossproduct = cma[1]*bma[0] - cma[0]*bma[1]
    if abs(crossproduct) > finfo(float32).eps:
        #print 'crossFail', abs(crossproduct), finfo(float32).eps
        return False

    dotproduct = cma[0]*bma[0] + cma[1]*bma[1]
    if dotproduct < 0:
        #print 'dotFail', dotProduct
        return False
    squaredLength = pow( bma[0], 2) + pow( bma[1], 2 )
    if dotproduct > squaredLength:
        #print 'squareFail',dotproduct,  squaredLength
        return False

    return True


def intersect( a1,a2, b1,b2 ) :
    point = intersectPoint( a1,a2, b1,b2 )
    #print 'point', point
    if point is None: return None

    #print 'a', isBetween(a1, a2, point)
    #print 'b', isBetween(b1, b2, point)
    if not isBetween(a1, a2, point): return None
    if not isBetween(b1, b2, point): return None

    return point

def dist( a,b, c ) :
    a = array(a)
    b = array(b)
    c = array(c)

    lineA = a-b 
    lineADist = sqrt( pow(lineA[0], 2) + pow(lineA[1], 2) )
    lineB = a-c
    lineBDist = sqrt( pow(lineB[0], 2) + pow(lineB[1], 2) )

    print 'dists', lineADist, lineBDist
    return lineBDist/lineADist    