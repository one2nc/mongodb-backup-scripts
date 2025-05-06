// Get the list of all databases
var dbs = db.adminCommand("listDatabases").databases;

// Filter out system databases
var filteredDbs = dbs.filter(database => !["admin", "config", "local"].includes(database.name));

// Iterate through each non-system database
var metadata = filteredDbs.map(database => {
    var dbName = database.name;
    var collections = db.getSiblingDB(dbName).getCollectionNames();

    var collectionData = collections.map(coll => {
        var collection = db.getSiblingDB(dbName).getCollection(coll);
        var count = collection.countDocuments();
        var size = collection.stats().size;

        // Get max _id
        var maxIdDoc = collection.find().sort({ _id: -1 }).limit(1).toArray();
        var maxIdValue = maxIdDoc.length > 0 ? maxIdDoc[0]._id : null;

        // Get min _id
        var minIdDoc = collection.find().sort({ _id: 1 }).limit(1).toArray();
        var minIdValue = minIdDoc.length > 0 ? minIdDoc[0]._id : null;

        return {
            collection: coll,
            document_count: count,
            collection_size_bytes: size,
            max_id: maxIdValue,
            min_id: minIdValue
        };
    });

    // Sort collections alphabetically within each database
    collectionData.sort((a, b) => a.collection.localeCompare(b.collection));

    return {
        database: dbName,
        collections: collectionData
    };
});

// Sort metadata by database name
metadata.sort((a, b) => a.database.localeCompare(b.database));

// Convert to JSON with indentation
var jsonOutput = JSON.stringify(metadata, null, 2);
print(jsonOutput);
