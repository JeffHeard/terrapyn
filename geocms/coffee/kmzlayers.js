// Generated by CoffeeScript 1.7.1
(function() {
  var KmzLayerSet, addlayers, imageLayer;

  imageLayer = function(mp, lyr) {
    var bounds, dst, ne, src, sw;
    src = mp.displayProjection;
    dst = mp.projection;
    sw = new OpenLayers.Geometry.Point(lyr.west, lyr.south);
    ne = new OpenLayers.Geometry.Point(lyr.east, lyr.north);
    sw = sw.transform(src, dst);
    ne = ne.transform(src, dst);
    bounds = new OpenLayers.Bounds(sw.x, sw.y, ne.x, ne.y);
    return new OpenLayers.Layer.Image(lyr.name, lyr.href, bounds, new OpenLayers.Size(lyr.width, lyr.height), {
      isBaseLayer: false,
      alwaysInRange: true
    });
  };

  addlayers = function(obj) {
    return function(layers) {
      var l, _i, _len, _ref, _results;
      obj.layers = (function() {
        var _i, _len, _results;
        _results = [];
        for (_i = 0, _len = layers.length; _i < _len; _i++) {
          l = layers[_i];
          _results.push(imageLayer(obj.map, l));
        }
        return _results;
      })();
      obj.map.addLayers(obj.layers);
      _ref = obj.layers;
      _results = [];
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        l = _ref[_i];
        _results.push(l.setVisibility(obj.visibility));
      }
      return _results;
    };
  };

  KmzLayerSet = (function() {
    function KmzLayerSet(map, identifier, name) {
      this.map = map;
      this.identifier = identifier;
      this.name = name;
      this.opacity = 1.0;
      this.layers = [];
      this.isCompound = true;
      this.visibility = true;
      this.kml = new OpenLayers.Layer.Vector(name, {
        projection: this.map.displayProjection,
        strategies: [new OpenLayers.Strategy.Fixed],
        protocol: new OpenLayers.Protocol.HTTP({
          url: "/ga_resources/kmz-features/" + this.identifier + "/",
          format: new OpenLayers.Format.KML({
            extractStyles: true,
            extractAttributes: true
          })
        })
      });
      this.map.addLayers([this.kml]);
      $.getJSON("/ga_resources/kmz-coverages/" + this.identifier + "/", addlayers(this));
    }

    KmzLayerSet.prototype.setVisibility = function(tf) {
      var l, _i, _len, _ref;
      if (this.layers.length) {
        _ref = this.layers;
        for (_i = 0, _len = _ref.length; _i < _len; _i++) {
          l = _ref[_i];
          l.setVisibility(tf);
        }
      }
      this.kml.setVisibility(tf);
      return this.visibility = tf;
    };

    KmzLayerSet.prototype.setOpacity = function(tf) {
      var l, _i, _len, _ref;
      if (this.layers.length) {
        _ref = this.layers;
        for (_i = 0, _len = _ref.length; _i < _len; _i++) {
          l = _ref[_i];
          l.setOpacity(tf);
        }
      }
      this.kml.setVisibility(tf);
      return this.opacity = tf;
    };

    return KmzLayerSet;

  })();

  window.KmzLayerSet = KmzLayerSet;

}).call(this);

//# sourceMappingURL=kmzlayers.map
