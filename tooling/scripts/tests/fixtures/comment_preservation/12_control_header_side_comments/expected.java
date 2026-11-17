public class Demo
{
    void run(boolean ready)
    {
        if (ready)  // trailing on if header
        {
            go();
        }
        if (ready)  // why return
        {
            return;
        }
        while (ready)  // on while
        {
            go();
        }
        for (String item : items)  // on enhanced for
        {
            use(item);
        }
        switch (mode)  // on switch
        {
            default:
                break;
        }
        synchronized (lock)  // on synchronized
        {
            go();
        }
        try (Resource r = open())  // on try-with-resources
        {
            go();
        }
        try  // on try
        {
            go();
        } finally {
            close();
        }
    }
}
