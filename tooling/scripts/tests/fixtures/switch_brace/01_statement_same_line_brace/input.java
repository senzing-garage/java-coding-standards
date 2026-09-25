public class Demo
{
    void run(Type type)
    {
        switch (type) {
            case ALPHA:
                doAlpha();
                break;
            default:
                doDefault();
        }
    }
}
