public class Demo
{
    void redo(SzEngine engine)
    {
        for (String redoRecord = engine.getRedoRecord();  // @highlight regex="redoRecord.*"
             redoRecord != null;
             redoRecord = engine.getRedoRecord())  // @highlight regex="redoRecord.*"
        {
            engine.processRedoRecord(redoRecord);
        }
        for (int index = 0;  /* cond */
             index < count;
             index++)
        {
            use(index);
        }
    }
}
