

//test1.findIndex( function(value){ return arraysEqual(value, [2,3]) } );

function arraysEqual(arr1, arr2) {
    if(arr1.length !== arr2.length)
        return false;
    for(var i = arr1.length; i--;) {
        if(arr1[i] !== arr2[i])
            return false;
    }

    return true;
}

function checkArry(value){ return arraysEqual(value, [1,2]) }

//Bokeh.documents[0]._all_models_by_name["_dict"].dynoPatch[7].data_source.change.emit()

//Bokeh.documents[0]._all_models_by_name._dict.dynoPatch[2].data_source.data.y = []

console.log('worked');
